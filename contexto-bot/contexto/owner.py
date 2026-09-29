"""Commands for the bot's owner (whoever owns the app in the Developer Portal).

They're mention commands (`@Contexto devguild set`) rather than slash commands,
so they work before any slash commands have been synced.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .store import Store

log = logging.getLogger("contexto")

DEV_GUILD_KEY = "dev_guild_id"


def dev_guild_id(store: Store) -> int | None:
    value = store.get_setting(DEV_GUILD_KEY)
    return int(value) if value else None


async def sync_commands(bot: commands.Bot, store: Store) -> str:
    """Dev server set: sync there only (instant). Otherwise sync globally."""
    gid = dev_guild_id(store)
    if gid:
        guild = discord.Object(gid)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        return f"Synced {len(synced)} commands to dev server {gid} (instant)."
    synced = await bot.tree.sync()
    return f"Synced {len(synced)} commands globally (can take a few minutes to appear)."


class Owner(commands.Cog):
    def __init__(self, bot: commands.Bot, store: Store):
        self.bot = bot
        self.store = store

    async def cog_check(self, ctx: commands.Context) -> bool:
        if await self.bot.is_owner(ctx.author):
            return True
        raise commands.NotOwner()

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("Only the bot's owner can use that.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("That isn't a valid server ID.", mention_author=False)
        else:
            log.exception("Owner command failed", exc_info=error)
            await ctx.reply(f"Failed: {error}", mention_author=False)

    @commands.group(name="devguild", invoke_without_command=True)
    async def devguild(self, ctx: commands.Context):
        """Show the dev server."""
        gid = dev_guild_id(self.store)
        if gid:
            guild = self.bot.get_guild(gid)
            name = guild.name if guild else "not a server I'm in"
            await ctx.reply(f"Dev server: **{name}** (`{gid}`). Slash commands sync there only.", mention_author=False)
        else:
            await ctx.reply(
                "No dev server set — slash commands sync globally.\n"
                "`@Contexto devguild set` makes this server the dev server.",
                mention_author=False,
            )

    @devguild.command(name="set")
    async def devguild_set(self, ctx: commands.Context, guild_id: int | None = None):
        """Make this server (or the given ID) the dev server and sync commands to it."""
        gid = guild_id or (ctx.guild and ctx.guild.id)
        if not gid:
            await ctx.reply("Run this in a server, or pass a server ID.", mention_author=False)
            return
        if self.bot.get_guild(gid) is None:
            await ctx.reply("I'm not in that server. Add me there first.", mention_author=False)
            return
        old = dev_guild_id(self.store)
        if old and old != gid:
            await self._clear_guild_commands(old)
        self.store.set_setting(DEV_GUILD_KEY, str(gid))
        await ctx.reply(await sync_commands(self.bot, self.store), mention_author=False)

    @devguild.command(name="clear")
    async def devguild_clear(self, ctx: commands.Context):
        """Stop using a dev server and sync commands globally."""
        old = dev_guild_id(self.store)
        if old:
            await self._clear_guild_commands(old)
        self.store.set_setting(DEV_GUILD_KEY, None)
        await ctx.reply(await sync_commands(self.bot, self.store), mention_author=False)

    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context):
        """Re-sync slash commands (after changing them)."""
        await ctx.reply(await sync_commands(self.bot, self.store), mention_author=False)

    async def _clear_guild_commands(self, gid: int) -> None:
        guild = discord.Object(gid)
        self.bot.tree.clear_commands(guild=guild)
        await self.bot.tree.sync(guild=guild)
