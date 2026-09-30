"""Message text and embeds, following the canvas design."""
from __future__ import annotations

import discord

from .engine import band, closeness

BLURPLE = 0x5865F2
GREEN = 0x57F287
AMBER = 0xF0B232
RED = 0xED4245

BAND_ICON = {"close": "🟩", "warm": "🟨", "cold": "🟥"}
MEDALS = ["🥇", "🥈", "🥉"]


def bar(rank: int, total: int, width: int = 12) -> str:
    filled = max(1, round(closeness(rank, total) * width))
    return "█" * filled + "░" * (width - filled)


def guess_line(rank: int, total: int) -> str:
    b = band(rank)
    return f"{BAND_ICON[b]} **#{rank:,}** `{bar(rank, total)}` {b}"


def guess_reply(rank: int, total: int, word: str, top, new_best: bool) -> str:
    """The rank line, plus the round's current top 3 in Discord's small grey subtext."""
    line = guess_line(rank, total)
    if new_best:
        line += " · **NEW BEST**"
    entries = []
    for r in top:
        entry = f"**{r['word']}** #{r['rank']:,}"
        if r["word"] == word:
            entry += " ↑ new"
        entries.append(entry)
    return f"{line}\n-# Top 3 · " + " · ".join(entries)


def _who(row) -> str:
    return "hint" if row["is_hint"] else f"<@{row['user_id']}>"


def board_embed(
    number: int, started_at: int, guesses: int, players: int, top, total: int,
    *, winner_id: int | None = None, secret: str | None = None, gave_up: bool = False,
) -> discord.Embed:
    if winner_id:
        color, status = GREEN, f"Solved by <@{winner_id}> — the word was **{secret}**."
    elif gave_up:
        color, status = RED, f"Round ended — the word was **{secret}**."
    else:
        color, status = BLURPLE, "Type one word in this channel to guess. Updates live."
    e = discord.Embed(title=f"Round #{number}", description=status, color=color)
    e.add_field(name="Guesses", value=f"{guesses:,}")
    e.add_field(name="Players", value=f"{players:,}")
    e.add_field(name="Started", value=f"<t:{started_at}:R>")
    if top:
        lines = [
            f"{BAND_ICON[band(r['rank'])]} `{'#' + format(r['rank'], ','):>7}` **{r['word']}** · {_who(r)}" for r in top
        ]
        e.add_field(name="Closest guesses", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Closest guesses", value="No guesses yet — be first.", inline=False)
    e.set_footer(text=f"Ranks go from 1 (the word) to {total:,}.")
    return e


def tiles(word: str) -> str:
    # Regional indicators, spaced so pairs don't merge into flags.
    return " ".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in word)


def _duration(seconds: int) -> str:
    h, rem = divmod(max(0, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"


def win_embed(
    number: int, secret: str, winner_id: int, guesses: int, players: int, seconds: int,
    runners_up, points: int, position: int, next_at: int,
) -> discord.Embed:
    e = discord.Embed(
        title=f"Round #{number} solved",
        description=f"{tiles(secret)}\n\n<@{winner_id}> guessed the secret word and earns **+1 point**.",
        color=GREEN,
    )
    e.add_field(name="Guesses", value=f"{guesses:,}")
    e.add_field(name="Players", value=f"{players:,}")
    e.add_field(name="Time", value=_duration(seconds))
    if runners_up:
        e.add_field(
            name="Closest runners-up",
            value="\n".join(f"<@{r['user_id']}> — {r['word']} `#{r['rank']:,}`" for r in runners_up),
            inline=False,
        )
    pts = "point" if points == 1 else "points"
    e.add_field(
        name="​",
        value=f"<@{winner_id}> now has **{points} {pts}** · **#{position}** on the server leaderboard\n"
        f"Next round starts <t:{next_at}:R>.",
        inline=False,
    )
    return e


def giveup_embed(number: int, secret: str, guesses: int, best, next_at: int) -> discord.Embed:
    e = discord.Embed(
        title=f"Round #{number} ended",
        description=f"{tiles(secret)}\n\nNobody found it. The word was **{secret}**.",
        color=RED,
    )
    e.add_field(name="Guesses", value=f"{guesses:,}")
    if best:
        e.add_field(name="Closest", value=f"{best['word']} `#{best['rank']:,}` · {_who(best)}")
    e.add_field(name="​", value=f"Next round starts <t:{next_at}:R>.", inline=False)
    return e


def leaderboard_embed(guild_name: str, period_label: str, rows, rounds_played: int, viewer_line: str) -> discord.Embed:
    e = discord.Embed(
        title=f"{guild_name} — Contexto leaderboard",
        description=f"{period_label} · 1 point per word found · {rounds_played:,} rounds played",
        color=AMBER,
    )
    if rows:
        lines = []
        for i, r in enumerate(rows):
            medal = MEDALS[i] if i < len(MEDALS) else f"`{i + 1}.`"
            pts = "pt" if r["points"] == 1 else "pts"
            lines.append(f"{medal} <@{r['user_id']}> — **{r['points']}** {pts} · fastest solve: {r['fastest']} guesses")
        e.add_field(name="Top 5", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Top 5", value="Nobody has found a word in this period yet.", inline=False)
    e.add_field(name="​", value=viewer_line, inline=False)
    return e


def stats_embed(user: discord.abc.User, points: int, position: int | None, activity, fastest) -> discord.Embed:
    e = discord.Embed(title=f"Contexto stats — {user.display_name}", color=BLURPLE)
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="Points", value=str(points))
    e.add_field(name="Rank", value=f"#{position}" if position else "—")
    e.add_field(name="Rounds played", value=str(activity["rounds"] or 0))
    e.add_field(name="Guesses", value=f"{activity['guesses'] or 0:,}")
    e.add_field(name="Fastest solve", value=f"{fastest} guesses" if fastest else "—")
    return e


def help_embed() -> discord.Embed:
    e = discord.Embed(title="How Contexto plays", color=BLURPLE)
    e.description = (
        "1. Only messages in the game channel count, and only single words.\n"
        "2. Every valid guess gets a rank from 1 to 50,000 — rank 1 is the secret word.\n"
        "3. Repeat guesses point to whoever tried them first.\n"
        "4. Unknown words get a ❓ reaction instead of a reply.\n"
        "5. First exact match wins the round: **+1 point**.\n"
        "6. A new round starts automatically after a cooldown."
    )
    e.add_field(name="Colors", value="🟩 close 1–300 · 🟨 warm 301–1,500 · 🟥 cold 1,501+", inline=False)
    e.add_field(
        name="Commands",
        value="`/contexto setup` `/contexto start` `/contexto board` `/contexto hint` "
        "`/contexto giveup` `/contexto help` `/contexto invite` `/contexto privacy` "
        "`/contexto forget-me` `/leaderboard` `/stats`",
        inline=False,
    )
    e.set_footer(text="By playing you agree to the Terms of Service. See /contexto privacy.")
    return e


def privacy_embed() -> discord.Embed:
    e = discord.Embed(title="Contexto & your data", color=BLURPLE)
    e.description = (
        "**What's stored:** your Discord user ID, the single-word guesses you make in the game channel "
        "with their rank and time, and the rounds you win.\n"
        "**What isn't:** any other message. The bot reads messages in the game channel only to check "
        "whether they're a guess.\n"
        "**Deleting it:** `/contexto forget-me` removes your guesses and points everywhere. "
        "Removing the bot from a server deletes that server's data."
    )
    return e
