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
from dotenv import load_dotenv, set_key

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


def ask_for_token() -> str:
    """First-run setup: prompt for the token and keep it in .env on this machine."""
    if not sys.stdin.isatty():
        sys.exit("No DISCORD_TOKEN set. Set it as an environment variable, or run `python bot.py` in a terminal once.")
    print(
        "First-time setup\n"
        "Paste your bot token from https://discord.com/developers/applications -> your app -> Bot -> Reset Token.\n"
        "It is saved to .env on this computer only. Never share it or commit it."
    )
    token = getpass.getpass("Bot token (hidden): ").strip()
    if token.count(".") != 2:
        sys.exit("That doesn't look like a bot token. Run again and paste the whole token.")
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), "DISCORD_TOKEN", token)
    print(f"Saved to {ENV_PATH}")
    return token


def main():
    load_dotenv(ENV_PATH)
    discord.utils.setup_logging(level=logging.INFO)
    token = os.getenv("DISCORD_TOKEN") or ask_for_token()
    terms_url, privacy_url = os.getenv("TERMS_URL"), os.getenv("PRIVACY_URL")
    if not (terms_url and privacy_url):
        log.warning("TERMS_URL / PRIVACY_URL not set; the bot's Terms and Privacy buttons are hidden.")
    try:
        space = WordSpace.load()
    except FileNotFoundError as e:
        sys.exit(str(e))
    log.info("Loaded %d words", len(space))
    store = Store(os.getenv("DATABASE_PATH", "contexto.db"))
    bot = ContextoBot(space, store, terms_url, privacy_url)
    try:
        bot.run(token, log_handler=None)
    except discord.LoginFailure:
        sys.exit(
            "Discord rejected the token. Reset it in the Developer Portal, delete the DISCORD_TOKEN line "
            f"from {ENV_PATH}, and run again."
        )


if __name__ == "__main__":
    main()
