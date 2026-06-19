"""Voice state updates: economy tracking, temp VC panels, join-to-create."""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.channels import delete_temp_vc_and_panel, resolve_temp_vc_category
from core.config import ECONOMY_ENABLED
from core.db import open_db
from core.vc_permissions import build_temp_vc_overwrites, get_vc_staff_roles
from database import get_guild_setting, now_utc
from handlers import vc_panel as vc_panel_handlers

logger = logging.getLogger(__name__)


async def handle_voice_state_update(
    bot: discord.Client,
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    """Track voice channel activity for economy rewards and handle join-to-create."""
    guild = member.guild
    if ECONOMY_ENABLED:
        now = now_utc()
        ch_before = before.channel if isinstance(before.channel, discord.VoiceChannel) else None
        ch_after = after.channel if isinstance(after.channel, discord.VoiceChannel) else None
        needs_voice_db = bool(ch_before) or (
            ch_after is not None and not (after.self_mute or after.self_deaf)
        )
        if needs_voice_db:
            async with open_db() as db:
                if ch_before:
                    await db.execute(
                        "DELETE FROM voice_activity WHERE guild_id=? AND user_id=? AND channel_id=?",
                        (guild.id, member.id, ch_before.id),
                    )
                if ch_after is not None and not (after.self_mute or after.self_deaf):
                    cur = await db.execute(
                        """
                        SELECT total_minutes FROM voice_activity
                        WHERE guild_id=? AND user_id=? AND channel_id=?
                        """,
                        (guild.id, member.id, ch_after.id),
                    )
                    row = await cur.fetchone()
                    existing_minutes = row[0] if row else 0
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO voice_activity
                        (guild_id, user_id, channel_id, joined_at, last_reward_at, total_minutes)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (guild.id, member.id, ch_after.id, now.isoformat(), None, existing_minutes),
                    )
                await db.commit()
        if ch_after is not None:
            try:
                from commands.moderation.inactive_role import maybe_clear_inactive_role

                await maybe_clear_inactive_role(member)
            except Exception:
                pass

    async def _maybe_refresh_vc_panel(
        channel: Optional[discord.VoiceChannel],
        *,
        db: Optional[aiosqlite.Connection] = None,
    ) -> None:
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return

        async def _is_temp_vc(conn: aiosqlite.Connection) -> bool:
            cur = await conn.execute(
                "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (guild.id, channel.id),
            )
            return await cur.fetchone() is not None

        try:
            if db is not None:
                if await _is_temp_vc(db):
                    await vc_panel_handlers.schedule_vc_panel_embed_update(bot, guild, channel.id)
                return
            async with open_db() as conn:
                if await _is_temp_vc(conn):
                    await vc_panel_handlers.schedule_vc_panel_embed_update(bot, guild, channel.id)
        except Exception:
            pass

    ch_before_vc = before.channel if isinstance(before.channel, discord.VoiceChannel) else None
    ch_after_vc = after.channel if isinstance(after.channel, discord.VoiceChannel) else None
    panel_channels = [c for c in (ch_before_vc, ch_after_vc) if c is not None]
    if panel_channels:
        async with open_db() as vc_db:
            for ch in panel_channels:
                await _maybe_refresh_vc_panel(ch, db=vc_db)

    if not after.channel:
        return

    create_id_s = await get_guild_setting(member.guild.id, "create_vc_channel_id")
    if not (create_id_s and create_id_s.isdigit()):
        return

    create_id = int(create_id_s)
    if after.channel.id != create_id:
        nonempty_channels = [
            ch
            for ch in (before.channel, after.channel)
            if ch and isinstance(ch, discord.VoiceChannel) and len(ch.members) > 0
        ]
        if nonempty_channels:
            now_iso = now_utc().isoformat()
            async with open_db() as db:
                for ch in nonempty_channels:
                    cur = await db.execute(
                        "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                        (guild.id, ch.id),
                    )
                    if await cur.fetchone():
                        await db.execute(
                            "UPDATE temp_vcs SET last_nonempty_at=? WHERE guild_id=? AND channel_id=?",
                            (now_iso, guild.id, ch.id),
                        )
                await db.commit()
        return

    category = await resolve_temp_vc_category(guild)
    create_ch = guild.get_channel(create_id)
    template_ch = create_ch if isinstance(create_ch, discord.VoiceChannel) else None
    staff_roles = await get_vc_staff_roles(guild)

    vc_name = f"{member.display_name} • Squad"
    overwrites = build_temp_vc_overwrites(
        guild,
        member,
        category=category,
        template_channel=template_ch,
        staff_roles=staff_roles,
    )

    new_vc = await guild.create_voice_channel(
        name=vc_name,
        category=category,
        overwrites=overwrites,
        reason="Join-to-create temp VC",
    )

    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) VALUES(?,?,?,?,?)",
            (guild.id, new_vc.id, member.id, now_utc().isoformat(), now_utc().isoformat()),
        )
        await db.commit()

    voice = member.voice
    if voice is None or voice.channel is None or voice.channel.id != create_id:
        logger.debug("[vc] %s left create channel before move; cleaning up %s", member.id, new_vc.id)
        try:
            await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (user left)")
        except Exception:
            pass
        return

    moved = False
    try:
        await member.move_to(new_vc, reason="Move to created squad VC")
        moved = True
    except discord.Forbidden:
        logger.debug("[vc] Missing Move Members permission for join-to-create")
    except discord.HTTPException as exc:
        if exc.code == 40032:
            logger.debug("[vc] move_to failed (not in voice) for %s; cleaning up %s", member.id, new_vc.id)
            try:
                await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (user disconnected)")
            except Exception:
                pass
            return
        logger.warning("[vc] move_to failed for %s: %s", member.id, exc)

    if not moved:
        if not new_vc.members:
            try:
                await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (move failed)")
            except Exception:
                pass
        return

    try:
        await vc_panel_handlers.post_vc_panel(bot, guild, new_vc, member)
    except Exception:
        pass
