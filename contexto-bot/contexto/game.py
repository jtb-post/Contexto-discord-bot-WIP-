"""The Contexto cog: listens in the game channel, ranks guesses, runs rounds."""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from . import render
from .engine import Ranking, WordSpace, load_secret_words, pick_secret
from .store import Store

log = logging.getLogger("contexto")

WORD_RE = re.compile(r"[a-z]+")
STRIP_CHARS = ".,!?;:'\"()[]{}*_~`|<>"
BOARD_REFRESH_DELAY = 2.0  # seconds; batches board edits during busy rounds

PERIODS = {"all": "All-time", "month": "This month", "week": "This week"}

# What the bot needs in a server; used for the invite link.
INVITE_PERMISSIONS = discord.Permissions(
    view_channel=True, send_messages=True, embed_links=True, read_message_history=True,
    add_reactions=True, manage_messages=True,  # manage_messages = pin the live board
)


def invite_url(application_id: int) -> str:
    return discord.utils.oauth_url(
        application_id, permissions=INVITE_PERMISSIONS, scopes=("bot", "applications.commands")
    )


def is_game_manager():
    """Manage Server, or the Game Manager role chosen in /contexto setup."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        cfg = interaction.client.get_cog("Contexto").store.get_guild(interaction.guild_id)
        role_id = cfg and cfg["manager_role_id"]
        if role_id and any(r.id == role_id for r in getattr(interaction.user, "roles", [])):
            return True
        raise app_commands.CheckFailure("not a game manager")
    return app_commands.check(predicate)


def now() -> int:
    return int(time.time())


def period_start(period: str) -> int:
    t = datetime.now(timezone.utc)
    if period == "month":
        return int(t.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    if period == "week":
        monday = (t - timedelta(days=t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(monday.timestamp())
    return 0


@dataclass
class RoundState:
    round_id: int
    guild_id: int
    number: int
    secret: str
    started_at: int
    ranking: Ranking
    hints_used: int = 0
    board_channel_id: int | None = None
    board_message_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    board_task: asyncio.Task | None = None


# --- persistent buttons (survive restarts via custom_id templates) -------------

class OpenLeaderboardButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ctx:lbopen"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="View leaderboard", style=discord.ButtonStyle.primary, custom_id="ctx:lbopen"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("Contexto").send_leaderboard(interaction, "all", ephemeral=True)


class PeriodButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ctx:lb:(?P<period>all|month|week):(?P<sel>[01])"):
    def __init__(self, period: str, selected: bool):
        super().__init__(
            discord.ui.Button(
                label=PERIODS[period],
                style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
                custom_id=f"ctx:lb:{period}:{int(selected)}",
            )
        )
        self.period = period

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["period"], match["sel"] == "1")

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("Contexto").send_leaderboard(interaction, self.period, edit=True)


class GuessesButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ctx:guesses:(?P<rid>\d+)"):
    def __init__(self, round_id: int, count: int | None = None):
        label = f"See all {count:,} guesses" if count else "See all guesses"
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"ctx:guesses:{round_id}"))
        self.round_id = round_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["rid"]))

    async def callback(self, interaction: discord.Interaction):
        await interaction.client.get_cog("Contexto").send_all_guesses(interaction, self.round_id)


DYNAMIC_ITEMS = (OpenLeaderboardButton, PeriodButton, GuessesButton)


def round_over_view(round_id: int, guess_count: int, next_at: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(OpenLeaderboardButton())
    view.add_item(GuessesButton(round_id, guess_count))
    mins = max(1, round((next_at - now()) / 60))
    view.add_item(discord.ui.Button(label=f"Next round in {mins} min", disabled=True))
    return view


def leaderboard_view(period: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for p in PERIODS:
        view.add_item(PeriodButton(p, p == period))
    return view


class ForgetMeView(discord.ui.View):
    def __init__(self, cog: "Contexto", user_id: int):
        super().__init__(timeout=60)
        self.cog, self.user_id = cog, user_id

    @discord.ui.button(label="Delete my data", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button isn't for you.", ephemeral=True)
            return
        self.cog.store.delete_user(self.user_id)
        for state in self.cog.rounds.values():
            self.cog._queue_board_refresh(state)
        self.stop()
        await interaction.response.edit_message(
            content="Done — your guesses and points were deleted from every server.", view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Nothing was deleted.", view=None)


# --- the cog -------------------------------------------------------------------

class Contexto(commands.Cog):
    contexto = app_commands.Group(name="contexto", description="Guess the secret word.", guild_only=True)

    def __init__(
        self, bot: commands.Bot, space: WordSpace, store: Store,
        terms_url: str | None = None, privacy_url: str | None = None,
    ):
        self.bot = bot
        self.space = space
        self.store = store
        self.terms_url = terms_url
        self.privacy_url = privacy_url
        self.secret_pool = load_secret_words(space)
        self.rounds: dict[int, RoundState] = {}
        self.pending: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        for row in self.store.active_rounds():
            if row["secret"] not in self.space:
                log.warning("Round %s secret %r missing from vocabulary; ending it", row["id"], row["secret"])
                self.store.end_round(row["id"], None, now(), self.store.round_stats(row["id"])[0])
                continue
            self.rounds[row["guild_id"]] = RoundState(
                round_id=row["id"], guild_id=row["guild_id"], number=row["number"], secret=row["secret"],
                started_at=row["started_at"], ranking=self.space.ranking(row["secret"]),
                hints_used=row["hints_used"], board_channel_id=row["board_channel_id"],
                board_message_id=row["board_message_id"],
            )
        for row in self.store.pending_rounds():
            if row["guild_id"] not in self.rounds:
                self._schedule(row["guild_id"], max(0, row["next_round_at"] - now()))
        log.info("Restored %d active rounds, %d scheduled", len(self.rounds), len(self.pending))

    async def cog_unload(self):
        for t in self.pending.values():
            t.cancel()
        for s in self.rounds.values():
            if s.board_task:
                s.board_task.cancel()

    # --- round lifecycle -------------------------------------------------------

    def _schedule(self, guild_id: int, delay: float) -> None:
        old = self.pending.pop(guild_id, None)
        if old:
            old.cancel()
        self.pending[guild_id] = asyncio.create_task(self._start_after(guild_id, delay))

    async def _start_after(self, guild_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self.bot.wait_until_ready()
            if guild_id in self.rounds:
                return
            cfg = self.store.get_guild(guild_id)
            channel = cfg and self.bot.get_channel(cfg["channel_id"])
            if channel is None:
                log.warning("Guild %s: game channel not found; not starting a round", guild_id)
                return
            self.pending.pop(guild_id, None)
            await self.start_round(guild_id, channel)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Failed to auto-start a round in guild %s", guild_id)

    async def start_round(self, guild_id: int, channel: discord.abc.Messageable) -> RoundState:
        task = self.pending.pop(guild_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        self.store.set_next_round_at(guild_id, None)

        secret = pick_secret(self.secret_pool, self.store.recent_secrets(guild_id))
        number = self.store.next_round_number(guild_id)
        t = now()
        round_id = self.store.create_round(guild_id, number, secret, t)
        state = RoundState(round_id, guild_id, number, secret, t, self.space.ranking(secret))
        self.rounds[guild_id] = state
        log.info("Guild %s: round #%s started", guild_id, number)
        await self._post_board(state, channel)
        return state

    async def _post_board(self, state: RoundState, channel) -> None:
        msg = await channel.send(embed=self._board(state))
        await self._unpin_board(state)
        state.board_channel_id, state.board_message_id = channel.id, msg.id
        self.store.set_board(state.round_id, channel.id, msg.id)
        try:
            await msg.pin(reason="Contexto live board")
        except discord.HTTPException:
            pass  # missing Manage Messages / pin limit: the board still works unpinned

    async def _unpin_board(self, state: RoundState) -> None:
        channel = state.board_channel_id and self.bot.get_channel(state.board_channel_id)
        if channel and state.board_message_id:
            try:
                await channel.get_partial_message(state.board_message_id).unpin()
            except discord.HTTPException:
                pass

    def _board(self, state: RoundState, *, winner_id: int | None = None, gave_up: bool = False) -> discord.Embed:
        guesses, players = self.store.round_stats(state.round_id)
        top = self.store.top_guesses(state.round_id, 6)
        over = winner_id is not None or gave_up
        return render.board_embed(
            state.number, state.started_at, guesses, players, top, len(self.space),
            winner_id=winner_id, secret=state.secret if over else None, gave_up=gave_up,
        )

    def _queue_board_refresh(self, state: RoundState) -> None:
        if state.board_task and not state.board_task.done():
            return
        state.board_task = asyncio.create_task(self._refresh_board(state, BOARD_REFRESH_DELAY))

    async def _refresh_board(self, state: RoundState, delay: float = 0, **final) -> None:
        if delay:
            await asyncio.sleep(delay)
        channel = state.board_channel_id and self.bot.get_channel(state.board_channel_id)
        if not channel or not state.board_message_id:
            return
        try:
            await channel.get_partial_message(state.board_message_id).edit(embed=self._board(state, **final))
        except discord.NotFound:
            state.board_message_id = None
        except discord.HTTPException:
            log.exception("Board edit failed")

    async def _end_round(self, state: RoundState, winner_id: int | None) -> tuple[int, int]:
        """Close the round, freeze the board, schedule the next. Returns (guess_count, next_at)."""
        self.rounds.pop(state.guild_id, None)
        guesses, _ = self.store.round_stats(state.round_id)
        self.store.end_round(state.round_id, winner_id, now(), guesses)
        if state.board_task:
            state.board_task.cancel()
        await self._refresh_board(state, winner_id=winner_id, gave_up=winner_id is None)
        await self._unpin_board(state)

        cfg = self.store.get_guild(state.guild_id)
        delay = (cfg["cooldown_min"] if cfg else 10) * 60
        next_at = now() + delay
        self.store.set_next_round_at(state.guild_id, next_at)
        self._schedule(state.guild_id, delay)
        return guesses, next_at

    def _standing(self, guild_id: int, user_id: int, since: int = 0) -> tuple[int, int | None, int | None]:
        """(points, position, fastest) for a user."""
        for i, row in enumerate(self.store.standings(guild_id, since), start=1):
            if row["user_id"] == user_id:
                return row["points"], i, row["fastest"]
        return 0, None, None

    # --- guessing --------------------------------------------------------------

    def links_view(self, include_invite: bool = True) -> discord.ui.View:
        view = discord.ui.View()
        if include_invite and self.bot.application_id:
            view.add_item(discord.ui.Button(label="Add to your server", url=invite_url(self.bot.application_id)))
        if self.terms_url:
            view.add_item(discord.ui.Button(label="Terms of Service", url=self.terms_url))
        if self.privacy_url:
            view.add_item(discord.ui.Button(label="Privacy Policy", url=self.privacy_url))
        return view

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        # Privacy Policy: a server's data is deleted when the bot is removed from it.
        task = self.pending.pop(guild.id, None)
        if task:
            task.cancel()
        state = self.rounds.pop(guild.id, None)
        if state and state.board_task:
            state.board_task.cancel()
        self.store.delete_guild(guild.id)
        log.info("Removed from guild %s; deleted its data", guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if self.bot.user and message.content.startswith((f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>")):
            return  # an owner command addressed to the bot, not a guess
        state = self.rounds.get(message.guild.id)
        cfg = state and self.store.get_guild(message.guild.id)
        if not cfg or cfg["channel_id"] != message.channel.id:
            return

        parts = message.content.split()
        if not parts:
            return  # attachments, stickers, etc.
        if len(parts) > 1:
            await message.reply("Ignored — one word per guess.", mention_author=False, delete_after=8)
            return
        word = parts[0].strip(STRIP_CHARS).lower()
        if not WORD_RE.fullmatch(word) or word not in self.space:
            try:
                await message.add_reaction("❓")
            except discord.HTTPException:
                pass
            return

        async with state.lock:
            if self.rounds.get(message.guild.id) is not state:
                return  # someone won while we waited on the lock
            prev = self.store.find_guess(state.round_id, word)
            if prev:
                who = "a hint" if prev["is_hint"] else f"<@{prev['user_id']}>"
                await message.reply(
                    f"Already guessed by {who} · #{prev['rank']:,}", mention_author=False, delete_after=10
                )
                return
            rank = state.ranking.rank(word)
            self.store.add_guess(state.round_id, word, message.author.id, rank, now())
            if rank == 1:
                await self._announce_win(state, message)
                return

        await message.reply(render.guess_line(rank, len(self.space)), mention_author=False)
        self._queue_board_refresh(state)

    async def _announce_win(self, state: RoundState, message: discord.Message) -> None:
        winner = message.author
        guesses, next_at = await self._end_round(state, winner.id)
        _, players = self.store.round_stats(state.round_id)
        points, position, _ = self._standing(state.guild_id, winner.id)
        embed = render.win_embed(
            state.number, state.secret, winner.id, guesses, players, now() - state.started_at,
            self.store.runners_up(state.round_id, winner.id), points, position or 1, next_at,
        )
        await message.reply(embed=embed, view=round_over_view(state.round_id, guesses, next_at), mention_author=False)

    # --- button handlers -------------------------------------------------------

    async def send_leaderboard(self, interaction: discord.Interaction, period: str, *, ephemeral=False, edit=False):
        guild = interaction.guild
        since = period_start(period)
        rows = self.store.standings(guild.id, since)
        points, position, _ = self._standing(guild.id, interaction.user.id, since)
        if position is None:
            viewer = "You haven't found a word in this period yet."
        elif position <= 5:
            viewer = f"You're **#{position}** with **{points}** point{'s' * (points != 1)}."
        else:
            gap = rows[4]["points"] - points
            viewer = f"You're **#{position}** with **{points}** point{'s' * (points != 1)} · {gap} behind #5"
        embed = render.leaderboard_embed(
            guild.name, PERIODS[period], rows[:5], self.store.rounds_played(guild.id, since), viewer
        )
        view = leaderboard_view(period)
        if edit:
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=ephemeral)

    async def send_all_guesses(self, interaction: discord.Interaction, round_id: int):
        rnd = self.store.get_round(round_id)
        if rnd is None or rnd["guild_id"] != interaction.guild_id:
            await interaction.response.send_message("That round no longer exists.", ephemeral=True)
            return
        rows = self.store.all_guesses(round_id)
        lines = [
            f"{'#' + format(r['rank'], ','):>7}  {r['word']:<20} {'(hint)' if r['is_hint'] else ''}".rstrip() for r in rows
        ]
        header = f"Round #{rnd['number']} — {len(rows):,} guesses, closest first"
        if len(lines) <= 25:
            await interaction.response.send_message(f"**{header}**\n```\n" + "\n".join(lines) + "\n```", ephemeral=True)
        else:
            data = (header + "\n\n" + "\n".join(lines)).encode("utf-8")
            file = discord.File(io.BytesIO(data), filename=f"round-{rnd['number']}-guesses.txt")
            await interaction.response.send_message(f"**{header}**", file=file, ephemeral=True)

    # --- slash commands --------------------------------------------------------

    @contexto.command(name="setup", description="Admin: choose the channel the game runs in.")
    @app_commands.describe(
        channel="Channel to play in", cooldown_minutes="Wait between rounds", hints_per_round="Hints allowed each round",
        manager_role="Role that can end rounds (people with Manage Server always can)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
        cooldown_minutes: app_commands.Range[int, 0, 1440] = 10,
        hints_per_round: app_commands.Range[int, 0, 10] = 3,
        manager_role: discord.Role | None = None,
    ):
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links and perms.read_message_history):
            await interaction.response.send_message(
                f"I need Send Messages, Embed Links and Read Message History in {channel.mention}.", ephemeral=True
            )
            return
        self.store.configure(
            interaction.guild_id, channel.id, cooldown_minutes, hints_per_round,
            manager_role.id if manager_role else None,
        )
        managers = f"{manager_role.mention} and Manage Server" if manager_role else "Manage Server only"
        msg = (
            f"Contexto will run in {channel.mention} · {cooldown_minutes} min between rounds · "
            f"{hints_per_round} hints per round · game managers: {managers}."
        )
        if interaction.guild_id in self.rounds:
            await interaction.response.send_message(msg + " The current round finishes first.", ephemeral=True)
            return
        await interaction.response.send_message(msg + " Starting round now.", ephemeral=True)
        await self.start_round(interaction.guild_id, channel)

    @contexto.command(name="start", description="Start a new round if none is running.")
    async def start(self, interaction: discord.Interaction):
        cfg = self.store.get_guild(interaction.guild_id)
        channel = cfg and self.bot.get_channel(cfg["channel_id"])
        if channel is None:
            await interaction.response.send_message("An admin needs to run `/contexto setup` first.", ephemeral=True)
            return
        if interaction.guild_id in self.rounds:
            await interaction.response.send_message(f"A round is already running in {channel.mention}.", ephemeral=True)
            return
        await interaction.response.send_message(f"New round starting in {channel.mention}.", ephemeral=True)
        await self.start_round(interaction.guild_id, channel)

    @contexto.command(name="board", description="Re-post the live board of closest guesses.")
    async def board(self, interaction: discord.Interaction):
        state = self.rounds.get(interaction.guild_id)
        cfg = self.store.get_guild(interaction.guild_id)
        if state is None or cfg is None:
            await interaction.response.send_message("No round is running.", ephemeral=True)
            return
        channel = self.bot.get_channel(cfg["channel_id"])
        await interaction.response.send_message("Board re-posted.", ephemeral=True)
        await self._post_board(state, channel)

    @contexto.command(name="hint", description="Reveal a word closer than the current best guess.")
    async def hint(self, interaction: discord.Interaction):
        state = self.rounds.get(interaction.guild_id)
        if state is None:
            await interaction.response.send_message("No round is running.", ephemeral=True)
            return
        cfg = self.store.get_guild(interaction.guild_id)
        async with state.lock:
            if state.hints_used >= cfg["hints_per_round"]:
                await interaction.response.send_message("No hints left this round.", ephemeral=True)
                return
            best = self.store.best_rank(state.round_id) or len(self.space)
            target = max(2, best // 2)
            while target > 1 and self.store.find_guess(state.round_id, state.ranking.word_at(target)):
                target -= 1
            if target <= 1 or target >= best:
                await interaction.response.send_message("You're already too close for a hint!", ephemeral=True)
                return
            word = state.ranking.word_at(target)
            self.store.add_guess(state.round_id, word, self.bot.user.id, target, now(), is_hint=True)
            self.store.use_hint(state.round_id)
            state.hints_used += 1
        left = cfg["hints_per_round"] - state.hints_used
        await interaction.response.send_message(
            f"💡 {interaction.user.mention} used a hint: **{word}** is {render.guess_line(target, len(self.space))} "
            f"· {left} left this round"
        )
        self._queue_board_refresh(state)

    @contexto.command(name="giveup", description="Game managers: end the round and reveal the word.")
    @is_game_manager()
    async def giveup(self, interaction: discord.Interaction):
        state = self.rounds.get(interaction.guild_id)
        if state is None:
            await interaction.response.send_message("No round is running.", ephemeral=True)
            return
        async with state.lock:
            if self.rounds.get(interaction.guild_id) is not state:
                await interaction.response.send_message("That round just ended.", ephemeral=True)
                return
            await interaction.response.defer()
            guesses, next_at = await self._end_round(state, None)
        top = self.store.top_guesses(state.round_id, 2)
        best = next((r for r in top if r["rank"] > 1), None)
        await interaction.followup.send(
            embed=render.giveup_embed(state.number, state.secret, guesses, best, next_at),
            view=round_over_view(state.round_id, guesses, next_at),
        )

    @contexto.command(name="help", description="How to play.")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=render.help_embed(), view=self.links_view(), ephemeral=True)

    @contexto.command(name="invite", description="Get a link to add Contexto to another server.")
    async def invite(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Anyone with Manage Server can add Contexto — no token or setup files needed.",
            view=self.links_view(), ephemeral=True,
        )

    @contexto.command(name="privacy", description="What Contexto stores, and links to the Terms and Privacy Policy.")
    async def privacy(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=render.privacy_embed(), view=self.links_view(include_invite=False), ephemeral=True
        )

    @contexto.command(name="forget-me", description="Delete your guesses and points from every server.")
    async def forget_me(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "This permanently deletes your guesses and points in every server Contexto is in. Continue?",
            view=ForgetMeView(self, interaction.user.id), ephemeral=True,
        )

    @app_commands.command(name="leaderboard", description="Top 5 Contexto players on this server.")
    @app_commands.guild_only()
    @app_commands.choices(period=[app_commands.Choice(name=v, value=k) for k, v in PERIODS.items()])
    async def leaderboard(self, interaction: discord.Interaction, period: app_commands.Choice[str] | None = None):
        await self.send_leaderboard(interaction, period.value if period else "all")

    @app_commands.command(name="stats", description="Contexto stats for you or another player.")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction, user: discord.Member | None = None):
        user = user or interaction.user
        points, position, fastest = self._standing(interaction.guild_id, user.id)
        activity = self.store.user_activity(interaction.guild_id, user.id)
        await interaction.response.send_message(embed=render.stats_embed(user, points, position, activity, fastest))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You need the Manage Server permission for that."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "Only game managers can do that (Manage Server, or the role set in `/contexto setup`)."
        else:
            log.exception("Command failed", exc_info=error)
            msg = "Something went wrong running that command."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
