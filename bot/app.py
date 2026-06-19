"""
Obsidian Clan Bot entry module.

Re-exports config/helpers for ``from bot import …`` backward compatibility,
wires the Discord client, and registers gateway events.
"""
from __future__ import annotations

import asyncio
import logging

import discord  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

from core.config import (  # noqa: E402
    TOKEN,
    GUILD_ID,
    MOD_ROLE_NAME,
    BOT_STATUS,
    TIMEZONE,
    DB_PATH,
    BOT_VERSION,
    BOT_CHANGELOG,
    TEMP_VC_CATEGORY_ID,
    TEMP_VC_CATEGORY_NAME,
    CREATE_VC_NAME,
    VOICE_PANEL_CHANNEL_ID,
    VOICE_PANEL_CHANNEL_NAME,
    COMPLAINTS_CHANNEL_ID,
    COMPLAINTS_CHANNEL_NAME,
    COMPLAINTS_LOG_CHANNEL_ID,
    COMPLAINTS_LOG_CHANNEL_NAME,
    EVENTS_CHANNEL_ID,
    EVENTS_CHANNEL_NAME,
    ECONOMY_ENABLED,
    AUTO_SETUP,
)
from core.channels import ensure_core_channels, resolve_channel_id  # noqa: E402
from database import add_coins, get_user_balance, transfer_coins, get_user_xp  # noqa: E402
from views import ComplaintPanel, ComplaintModView, RSVPView  # noqa: E402
from bot.client import ClanBot, create_bot  # noqa: E402
from handlers.automod import check_auto_mod  # noqa: E402
from handlers import vc_panel as _vc_panel_handlers  # noqa: E402
from handlers.discord_events import register_discord_events  # noqa: E402

__all__ = [
    "bot",
    "ClanBot",
    "check_auto_mod",
    "post_vc_panel",
    "update_vc_panel_embed",
    "log_complaint_action",
    "detect_and_update_version",
    "TOKEN",
    "GUILD_ID",
    "MOD_ROLE_NAME",
    "BOT_STATUS",
    "TIMEZONE",
    "DB_PATH",
    "BOT_VERSION",
    "BOT_CHANGELOG",
    "TEMP_VC_CATEGORY_ID",
    "TEMP_VC_CATEGORY_NAME",
    "CREATE_VC_NAME",
    "VOICE_PANEL_CHANNEL_ID",
    "VOICE_PANEL_CHANNEL_NAME",
    "COMPLAINTS_CHANNEL_ID",
    "COMPLAINTS_CHANNEL_NAME",
    "COMPLAINTS_LOG_CHANNEL_ID",
    "COMPLAINTS_LOG_CHANNEL_NAME",
    "EVENTS_CHANNEL_ID",
    "EVENTS_CHANNEL_NAME",
    "ECONOMY_ENABLED",
    "AUTO_SETUP",
    "ensure_core_channels",
    "resolve_channel_id",
    "ComplaintPanel",
    "ComplaintModView",
    "RSVPView",
    "add_coins",
    "get_user_balance",
    "transfer_coins",
    "get_user_xp",
]


def detect_and_update_version(*args, **kwargs):
    from core.version_tracking import detect_and_update_version as _fn

    return _fn(*args, **kwargs)


bot = create_bot()
register_discord_events(bot)


async def log_complaint_action(
    guild: discord.Guild, case_id: str, actor_id: int, action: str, note: str = ""
) -> None:
    from database import log_complaint_action as _db_log_complaint

    await _db_log_complaint(guild.id, case_id, actor_id, action, note, guild=guild, bot=bot)


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    await _vc_panel_handlers.post_vc_panel(bot, guild, vc, owner)


async def update_vc_panel_embed(guild: discord.Guild, vc_id: int, *, force: bool = False) -> None:
    await _vc_panel_handlers.update_vc_panel_embed(bot, guild, vc_id, force=force)


async def schedule_vc_panel_embed_update(guild: discord.Guild, vc_id: int) -> None:
    await _vc_panel_handlers.schedule_vc_panel_embed_update(bot, guild, vc_id)


async def main():
    from bot.runner import run_bot

    await run_bot(bot)


if __name__ == "__main__":
    asyncio.run(main())
