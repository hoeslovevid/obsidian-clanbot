import os
import re
import time
import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, Union

import aiosqlite  # type: ignore
import aiohttp  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore
from discord.ext import commands, tasks  # type: ignore
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True  # Force reconfiguration if already configured
)
logger = logging.getLogger(__name__)

# ============================================================
# Obsidian Clan Bot (Warframe Discord)
# - Join-to-create temporary voice channels in "Temp VCs"
# - Obsidian voice control panels (buttons + modals)
# - Complaints desk (button -> modal -> case embed + staff thread)
# - Ops events (natural language time parsing, RSVP, reminder)
# ============================================================

# Import config first (loads env, no heavy deps)
from core.db import open_db, is_db_locked_error
from core.config import (
    TOKEN, GUILD_ID, MOD_ROLE_NAME, BOT_STATUS, TIMEZONE, DB_PATH,
    BOT_VERSION, BOT_CHANGELOG,
    TEMP_VC_CATEGORY_ID, TEMP_VC_CATEGORY_NAME, CREATE_VC_NAME,
    VOICE_IDLE_DELETE_MINUTES, VC_CLEANUP_INTERVAL_MINUTES, VC_PANEL_UPDATE_DEBOUNCE_SECONDS,
    VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME,
    COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME,
    COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME,
    EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME,
    ECONOMY_ENABLED, COINS_PER_MESSAGE, COINS_PER_MINUTE_VOICE,
    COINS_DAILY_REWARD, MESSAGE_COOLDOWN_SECONDS,
    VOICE_REWARD_INTERVAL_MINUTES, MIN_VOICE_MINUTES_FOR_REWARD,
    EVENT_REMINDER_MINUTES_BEFORE, EVENT_REMINDER_LOOP_MINUTES,
    AUTO_SETUP, OPENAI_API_KEY,
)

# Re-export config for modules that import from bot (backward compat)
__all__ = [
    "bot", "check_auto_mod", "post_vc_panel", "update_vc_panel_embed", "log_complaint_action",
    "TOKEN", "GUILD_ID", "MOD_ROLE_NAME", "BOT_STATUS", "TIMEZONE", "DB_PATH",
    "BOT_VERSION", "BOT_CHANGELOG",
    "TEMP_VC_CATEGORY_ID", "TEMP_VC_CATEGORY_NAME", "CREATE_VC_NAME",
    "VOICE_PANEL_CHANNEL_ID", "VOICE_PANEL_CHANNEL_NAME",
    "COMPLAINTS_CHANNEL_ID", "COMPLAINTS_CHANNEL_NAME",
    "COMPLAINTS_LOG_CHANNEL_ID", "COMPLAINTS_LOG_CHANNEL_NAME",
    "EVENTS_CHANNEL_ID", "EVENTS_CHANNEL_NAME",
    "ECONOMY_ENABLED", "AUTO_SETUP",
    "ensure_core_channels", "resolve_channel_id", "ComplaintPanel",
    "ComplaintModView", "RSVPView", "add_coins", "get_user_balance",
    "transfer_coins", "get_user_xp", "detect_and_update_version",
]

# Intents
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.presences = True
INTENTS.voice_states = True

# Import utilities and modules (avoid heavy: tasks, version_tracking, warframe_api)
from core.utils import obsidian_embed, extract_id, get_mod_role, is_mod, parse_time_natural, display_case_status
from database import (
    get_user_balance, add_coins, remove_coins, transfer_coins,
    get_user_xp, add_xp, calculate_level, xp_for_level, xp_for_next_level,
    get_guild_setting, set_guild_setting, now_utc, init_db,
)
from core.channels import (
    resolve_channel_id, find_or_create_text_channel,
    resolve_temp_vc_category, ensure_join_to_create_channel, ensure_core_channels,
    delete_temp_vc_and_panel, delete_vc_panel_message
)
from core.modals import RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal, ComplaintModal, RequestInfoModal
from views import VCPanelView, ComplaintPanel, ComplaintModView, RSVPView, SetLimitView, SetLimitSelect
# tasks and version_tracking: lazy-import to defer ~2k lines until needed
def detect_and_update_version(*args, **kwargs):
    """Lazy wrapper - loads version_tracking only when called (e.g. /force_version_update)."""
    from core.version_tracking import detect_and_update_version as _fn
    return _fn(*args, **kwargs)




# Modal deduplication set now lives in handlers/modal_handler.py

# --------------------- Bot ---------------------
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.start_time = now_utc()

    async def setup_hook(self):
        from core.db import attach_bot_database

        attach_bot_database(self)

        # Sync commands only when BOT_VERSION changes (saves Discord API churn on restarts).
        from core.config import PROJECT_ROOT

        sync_marker = PROJECT_ROOT / "data" / ".command_sync_version"
        if sync_marker.is_file() and sync_marker.read_text(encoding="utf-8").strip() == BOT_VERSION:
            from core.command_tree_stats import collect_command_tree_stats

            self._command_tree_stats = collect_command_tree_stats(self)
            from core.command_sync import should_use_guild_sync

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
            # discord.py CommandSyncFailure attributes vary by version; use getattr for type checkers
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
                                    print(f"[sync] ERROR: Command '{cmd.name}' has choice '{choice.name}' with {len(choice.name)} characters!")
                elif isinstance(cmd, app_commands.Group):
                    for subcmd in cmd.commands:
                        for param in getattr(subcmd, "parameters", []):
                            if getattr(param, "choices", None):
                                for choice in param.choices:
                                    if len(choice.name) >= 25:
                                        print(f"[sync] ERROR: Group '{cmd.name}' subcommand '{subcmd.name}' has choice '{choice.name}' with {len(choice.name)} characters!")
            import traceback
            traceback.print_exc()
        except Exception as e:
            print(f"[sync] Failed to sync commands: {e}")
            import traceback
            traceback.print_exc()


bot = ClanBot()

# Load commands from commands_loader (cleaner, easier to debug)
from core.commands_loader import load_all_commands
load_all_commands(bot)

from handlers.incident_checks import install_incident_mode_checks

install_incident_mode_checks(bot)


async def log_complaint_action(
    guild: discord.Guild, case_id: str, actor_id: int, action: str, note: str = ""
) -> None:
    from database import log_complaint_action as _db_log_complaint

    await _db_log_complaint(guild.id, case_id, actor_id, action, note, guild=guild, bot=bot)


# Database initialization is now in database.py


from handlers.automod import check_auto_mod
from handlers import vc_panel as _vc_panel_handlers


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    """Post a VC control panel message."""
    await _vc_panel_handlers.post_vc_panel(bot, guild, vc, owner)


async def update_vc_panel_embed(guild: discord.Guild, vc_id: int, *, force: bool = False) -> None:
    """Edit the VC panel message with live member count and lock status."""
    await _vc_panel_handlers.update_vc_panel_embed(bot, guild, vc_id, force=force)


async def schedule_vc_panel_embed_update(guild: discord.Guild, vc_id: int) -> None:
    """Coalesce voice-triggered VC panel refreshes per guild."""
    await _vc_panel_handlers.schedule_vc_panel_embed_update(bot, guild, vc_id)


# --------------------- Economy Event Handlers ---------------------
@bot.event
async def on_message(message: discord.Message):
    from handlers.message_events import handle_on_message

    await handle_on_message(bot, message)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    from handlers.voice_events import handle_voice_state_update

    await handle_voice_state_update(bot, member, before, after)


# --------------------- Component Router ---------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    from handlers.interaction_router import handle_interaction

    await handle_interaction(bot, interaction)


# --------------------- Join-to-create logic ---------------------
# Background tasks are now in tasks.py and started via setup_tasks() in on_ready


# --------------------- Economy Commands ---------------------
# Economy commands are now loaded from commands/economy/ folder via load_all_commands()


# --------------------- Update Log Functions ---------------------
# Version tracking functions moved to version_tracking.py

# --------------------- Install / startup hooks ---------------------
@bot.event
async def on_guild_join(guild: discord.Guild):
    from handlers.guild_events import handle_guild_join

    await handle_guild_join(bot, guild)


@bot.event
async def on_guild_remove(guild: discord.Guild):
    from handlers.guild_events import handle_guild_remove

    await handle_guild_remove(bot, guild)


@bot.event
async def on_ready():
    """Bot ready event — delegates to handlers/startup.py for startup tasks."""
    from handlers.startup import run_startup
    await run_startup(bot)


# Cache for achievement definitions moved to handlers/member_events.py


@bot.event
async def on_member_join(member: discord.Member):
    from handlers.member_events import handle_member_join

    await handle_member_join(bot, member)


@bot.event
async def on_member_remove(member: discord.Member):
    from handlers.member_events import handle_member_remove

    await handle_member_remove(bot, member)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    from handlers.reactions import handle_raw_reaction_add

    await handle_raw_reaction_add(bot, payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    from handlers.reactions import handle_raw_reaction_remove

    await handle_raw_reaction_remove(bot, payload)


@bot.event
async def on_message_delete(message: discord.Message):
    from handlers.message_logs import handle_message_delete

    await handle_message_delete(bot, message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    from handlers.message_logs import handle_message_edit

    await handle_message_edit(bot, before, after)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    from handlers.message_logs import handle_member_ban

    await handle_member_ban(bot, guild, user)


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    from handlers.command_tracking import handle_app_command_completion

    await handle_app_command_completion(bot, interaction, command)


def _find_similar_commands(typed: str, all_commands: list[str], max_suggestions: int = 3) -> list[str]:
    """Find commands similar to typed (simple prefix/substring match)."""
    typed_lower = typed.lower().strip()
    if not typed_lower:
        return []
    suggestions = []
    for c in all_commands:
        cl = c.lower()
        if cl == typed_lower:
            return []  # Exact match, no suggestion needed
        if cl.startswith(typed_lower) or typed_lower in cl:
            suggestions.append(c)
    # Sort by relevance (prefix matches first, then by length)
    suggestions.sort(key=lambda x: (not x.lower().startswith(typed_lower), len(x)))
    return suggestions[:max_suggestions]


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle application command errors with user-friendly messages."""
    from core.error_handling import handle_app_command_error

    await handle_app_command_error(
        bot,
        interaction,
        error,
        find_similar_commands=_find_similar_commands,
    )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    from handlers.message_logs import handle_member_update

    await handle_member_update(bot, before, after)


async def main():
    from bot.runner import run_bot

    await run_bot(bot)


if __name__ == "__main__":
    asyncio.run(main())
