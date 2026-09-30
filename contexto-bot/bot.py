"""Entry point: python bot.py

The first run asks for the bot token and saves it to .env on this machine
(never in the code, and .env is git-ignored). Hosting services can set the
DISCORD_TOKEN environment variable instead.
"""
from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import dotenv_values, load_dotenv, set_key, unset_key

from contexto.engine import WordSpace
from contexto.game import DYNAMIC_ITEMS, Contexto, invite_url
from contexto.owner import Owner, sync_commands
from contexto.store import Store

log = logging.getLogger("contexto")
ENV_PATH = Path(__file__).resolve().parent / ".env"


class ContextoBot(commands.Bot):
    def __init__(self, space: WordSpace, store: Store, terms_url: str | None, privacy_url: str | None):
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read guesses
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Game("Contexto · /contexto help"),
            help_command=None,
        )
        self.space, self.store = space, store
        self.terms_url, self.privacy_url = terms_url, privacy_url

    async def setup_hook(self):
        await self.add_cog(Contexto(self, self.space, self.store, self.terms_url, self.privacy_url))
        await self.add_cog(Owner(self, self.store))
        self.add_dynamic_items(*DYNAMIC_ITEMS)
        log.info(await sync_commands(self, self.store))

    async def on_ready(self):
        log.info("Logged in as %s in %d servers", self.user, len(self.guilds))
        log.info("Invite link: %s", invite_url(self.application_id))
        # The bot ignores every message until a server runs /contexto setup, so say so here.
        if not self.guilds:
            log.warning("The bot isn't in any server yet. Open the invite link above to add it.")
        for guild in self.guilds:
            self.warn_if_not_set_up(guild)

    async def on_guild_join(self, guild: discord.Guild):
        log.info("Added to server %s", guild.name)
        self.warn_if_not_set_up(guild)

    def warn_if_not_set_up(self, guild: discord.Guild):
        if not self.store.get_guild(guild.id):
            log.warning(
                "Not set up in %s yet: run /contexto setup there and pick the game channel. "
                "Until then the bot ignores messages in that server.", guild.name,
            )


SETUP_ERROR = 2  # tells Start Contexto.bat to stop and show the message instead of restarting


def fail(message: str):
    print(f"\n{message}", file=sys.stderr)
    sys.exit(SETUP_ERROR)


def ask_for_token() -> str:
    """First-run setup: prompt for the token and keep it in .env on this machine."""
    if not sys.stdin.isatty():
        fail("No DISCORD_TOKEN set. Set it as an environment variable, or run `python bot.py` in a terminal once.")
    print(
        "First-time setup\n"
        "Paste your bot token from https://discord.com/developers/applications -> your app -> Bot -> Reset Token.\n"
        "It is saved to .env on this computer only. Never share it or commit it."
    )
    token = getpass.getpass("Bot token (hidden): ").strip()
    if token.count(".") != 2:
        fail("That doesn't look like a bot token. Run again and paste the whole token.")
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "DISCORD_TOKEN", token)
    print(f"Saved to {ENV_PATH}")
    return token


def main():
    load_dotenv(ENV_PATH)
    discord.utils.setup_logging(level=logging.INFO)
    # The bot never joins voice, so discord.py's "voice will NOT be supported" warnings are noise.
    logging.getLogger("discord.client").addFilter(lambda r: "voice will NOT be supported" not in r.getMessage())
    token = os.getenv("DISCORD_TOKEN") or ask_for_token()
    terms_url, privacy_url = os.getenv("TERMS_URL"), os.getenv("PRIVACY_URL")
    if not (terms_url and privacy_url):
        log.warning("TERMS_URL / PRIVACY_URL not set; the bot's Terms and Privacy buttons are hidden.")
    try:
        space = WordSpace.load()
    except FileNotFoundError as e:
        fail(str(e))
    log.info("Loaded %d words", len(space))
    store = Store(os.getenv("DATABASE_PATH") or ENV_PATH.parent / "contexto.db")
    bot = ContextoBot(space, store, terms_url, privacy_url)
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        saved = ENV_PATH.exists() and dotenv_values(ENV_PATH).get("DISCORD_TOKEN") == token
        if saved:
            unset_key(str(ENV_PATH), "DISCORD_TOKEN")
        fail(
            "Discord rejected the token" + (", so it was removed from .env" if saved else "") + ".\n"
            "Get a new one (Developer Portal -> Bot -> Reset Token) and start again; you'll be asked for it."
        )
    except discord.PrivilegedIntentsRequired:
        fail(
            "Message Content Intent is off. Turn it on in the Developer Portal -> your app -> Bot -> "
            "Privileged Gateway Intents, save, and start again."
        )


if __name__ == "__main__":
    main()
