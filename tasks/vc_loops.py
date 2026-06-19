"""Temporary voice channel cleanup (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.channels import delete_temp_vc_and_panel, resolve_channel_id
from core.config import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
from database import DB_PATH, get_guild_setting, now_utc

logger = logging.getLogger(__name__)

VOICE_IDLE_DELETE_MINUTES = int(__import__("os").getenv("VOICE_IDLE_DELETE_MINUTES", "5"))


async def run_temp_vc_cleanup_cycle(bot: discord.Client) -> None:
    # Item 47: expire stale revival vote messages each cycle.
    try:
        from commands.voice.vc import expire_pending_revivals
        await expire_pending_revivals(bot)
    except Exception as e:
        logger.debug(f"[vc-revival] expire pass failed: {e}")
    cutoff = now_utc() - timedelta(minutes=VOICE_IDLE_DELETE_MINUTES)
    for guild in bot.guilds:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, last_nonempty_at FROM temp_vcs WHERE guild_id=?",
                (guild.id,),
            )
            rows = await cur.fetchall()
        for channel_id, last_nonempty_at in rows:
            vc = guild.get_channel(int(channel_id))
            if not isinstance(vc, discord.VoiceChannel):
                await delete_temp_vc_and_panel(guild, int(channel_id), reason="Cleanup missing VC", bot=bot)
                continue
            # Never delete join-to-create trigger
            create_id_s = await get_guild_setting(guild.id, "create_vc_channel_id")
            if create_id_s and create_id_s.isdigit() and vc.id == int(create_id_s):
                continue
            try:
                last_dt = datetime.fromisoformat(last_nonempty_at)
            except Exception:
                last_dt = now_utc()
            if len(vc.members) == 0 and last_dt < cutoff:
                # Item 47: post a revival-vote message in the panel channel
                # BEFORE we delete the VC, so the metadata is still readable.
                try:
                    from commands.voice.vc import _record_revival_intent
                    from core.channels import resolve_channel_id
                    from bot import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
                    panel_ch_id = await resolve_channel_id(
                        guild, "voice_panel_channel_id",
                        VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME,
                    )
                    panel_ch = guild.get_channel(panel_ch_id) if panel_ch_id else None
                    if isinstance(panel_ch, discord.TextChannel):
                        await _record_revival_intent(guild, vc, log_channel=panel_ch)
                except Exception as e:
                    logger.debug(f"[vc-revival] could not record revival intent: {e}")
                await delete_temp_vc_and_panel(guild, vc.id, reason="Temp VC idle cleanup", bot=bot)

