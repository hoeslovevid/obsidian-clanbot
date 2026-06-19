"""Discord client (ClanBot) and command-tree setup."""
from __future__ import annotations

import logging
import traceback
from typing import Any

import discord  # type: ignore
from discord import app_commands  # type: ignore
from discord.ext import commands  # type: ignore

from core.config import BOT_VERSION, GUILD_ID, PROJECT_ROOT
from database import now_utc

logger = logging.getLogger(__name__)

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.presences = True
INTENTS.voice_states = True


class ClanBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=INTENTS)
        self.start_time = now_utc()

    async def setup_hook(self) -> None:
        from core.db import attach_bot_database

        attach_bot_database(self)

        sync_marker = PROJECT_ROOT / "data" / ".command_sync_version"
        if sync_marker.is_file() and sync_marker.read_text(encoding="utf-8").strip() == BOT_VERSION:
            from core.command_tree_stats import collect_command_tree_stats
            from core.command_sync import should_use_guild_sync

            self._command_tree_stats = collect_command_tree_stats(self)
            scope = f"guild {GUILD_ID}" if should_use_guild_sync() else "global"
            print(f"[sync] Skipping command sync — BOT_VERSION {BOT_VERSION} unchanged ({scope})")
            return

        from core.command_sync import sync_app_commands

        try:
            sync_guild_id, self._command_tree_stats = await sync_app_commands(self)
            self._last_command_sync = now_utc()
            self._command_sync_guild_id = sync_guild_id
            try:
                sync_marker.parent.mkdir(parents=True, exist_ok=True)
                sync_marker.write_text(BOT_VERSION, encoding="utf-8")
            except Exception as sync_err:
                logger.debug("[sync] Could not write sync version marker: %s", sync_err)
        except discord.app_commands.errors.CommandSyncFailure as e:
            print(f"[sync] Failed to sync commands: {e}")
            err: Any = e
            errs = getattr(err, "errors", None)
            if errs:
                print(f"[sync] Error details: {errs}")
            cmd_list = getattr(err, "commands", None) or []
            print(f"[sync] Commands being synced: {len(cmd_list)}")
            for cmd in cmd_list:
                if isinstance(cmd, app_commands.Command):
                    for param in getattr(cmd, "parameters", []):
                        if getattr(param, "choices", None):
                            for choice in param.choices:
                                if len(choice.name) >= 25:
                                    print(
                                        f"[sync] ERROR: Command '{cmd.name}' has choice "
                                        f"'{choice.name}' with {len(choice.name)} characters!"
                                    )
                elif isinstance(cmd, app_commands.Group):
                    for subcmd in cmd.commands:
                        for param in getattr(subcmd, "parameters", []):
                            if getattr(param, "choices", None):
                                for choice in param.choices:
                                    if len(choice.name) >= 25:
                                        print(
                                            f"[sync] ERROR: Group '{cmd.name}' subcommand "
                                            f"'{subcmd.name}' has choice '{choice.name}' with "
                                            f"{len(choice.name)} characters!"
                                        )
            traceback.print_exc()
        except Exception as e:
            print(f"[sync] Failed to sync commands: {e}")
            traceback.print_exc()


def create_bot() -> ClanBot:
    """Construct ClanBot, load slash commands, and install global checks."""
    bot = ClanBot()
    from core.commands_loader import load_all_commands

    load_all_commands(bot)
    from handlers.incident_checks import install_incident_mode_checks

    install_incident_mode_checks(bot)
    return bot
