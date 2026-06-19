"""Temporary VC control panel helpers (extracted from bot/app.py)."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Tuple

import discord  # type: ignore

from core.channels import resolve_channel_id
from core.config import (
    VC_PANEL_UPDATE_DEBOUNCE_SECONDS,
    VOICE_PANEL_CHANNEL_ID,
    VOICE_PANEL_CHANNEL_NAME,
)
from core.db import open_db
from core.utils import obsidian_embed
from views import VCPanelView

logger = logging.getLogger(__name__)

_vc_panel_fingerprint: Dict[Tuple[int, int], str] = {}
_guild_pending_vc_updates: Dict[int, set[int]] = {}
_guild_vc_flush_tasks: Dict[int, asyncio.Task] = {}


async def post_vc_panel(
    bot: discord.Client,
    guild: discord.Guild,
    vc: discord.VoiceChannel,
    owner: discord.Member,
) -> None:
    """Post a VC control panel message."""
    panel_ch_id = await resolve_channel_id(
        guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
    )
    if not panel_ch_id:
        return
    panel_ch = guild.get_channel(panel_ch_id)
    if not isinstance(panel_ch, discord.TextChannel):
        return

    everyone_ow = vc.overwrites_for(guild.default_role)
    locked = everyone_ow.connect is False
    members = len(vc.members)
    cap = vc.user_limit if vc.user_limit else "∞"
    lock_label = "🔒 Sealed" if locked else "🔓 Open"

    embed = obsidian_embed(
        "Voice Channel Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner.mention}\n"
        f"**Members:** {members}/{cap}\n"
        f"**Status:** {lock_label}\n\n"
        "Configure your voice channel using the controls below.\n"
        "_Squad owners and configured staff roles can use these controls._",
        color=discord.Color.dark_grey(),
        client=bot,
    )
    view = VCPanelView(vc.id)
    msg = await panel_ch.send(embed=embed, view=view)

    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO vc_panels(guild_id, channel_id, message_id) VALUES(?,?,?)",
            (guild.id, vc.id, msg.id),
        )
        await db.commit()

    bot.add_view(view)


async def update_vc_panel_embed(
    bot: discord.Client,
    guild: discord.Guild,
    vc_id: int,
    *,
    force: bool = False,
) -> None:
    """Edit the VC panel message with live member count and lock status."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT message_id FROM vc_panels WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        row = await cur.fetchone()
    if not row:
        return

    vc = guild.get_channel(vc_id)
    if not isinstance(vc, discord.VoiceChannel):
        return

    panel_ch_id = await resolve_channel_id(
        guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
    )
    panel_ch = guild.get_channel(panel_ch_id) if panel_ch_id else None
    if not isinstance(panel_ch, discord.TextChannel):
        return

    async with open_db() as db:
        cur = await db.execute(
            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        owner_row = await cur.fetchone()
    owner_id = int(owner_row[0]) if owner_row else 0
    owner = guild.get_member(owner_id)
    owner_line = owner.mention if owner else f"<@{owner_id}>" if owner_id else "—"

    everyone_ow = vc.overwrites_for(guild.default_role)
    locked = everyone_ow.connect is False
    members = len(vc.members)
    cap = vc.user_limit if vc.user_limit else "∞"
    lock_label = "🔒 Sealed" if locked else "🔓 Open"

    fingerprint = f"{members}|{cap}|{locked}|{owner_id}"
    fp_key = (guild.id, vc_id)
    if not force and _vc_panel_fingerprint.get(fp_key) == fingerprint:
        return

    embed = obsidian_embed(
        "Voice Channel Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner_line}\n"
        f"**Members:** {members}/{cap}\n"
        f"**Status:** {lock_label}\n\n"
        "Configure your voice channel using the controls below.\n"
        "_Squad owners and configured staff roles can use these controls._",
        color=discord.Color.dark_grey(),
        client=bot,
    )

    try:
        from core.safe_message_edit import safe_message_edit

        msg = await panel_ch.fetch_message(int(row[0]))
        await safe_message_edit(msg, embed=embed, view=VCPanelView(vc_id))
        _vc_panel_fingerprint[fp_key] = fingerprint
    except Exception:
        pass


async def schedule_vc_panel_embed_update(
    bot: discord.Client,
    guild: discord.Guild,
    vc_id: int,
) -> None:
    """Coalesce voice-triggered VC panel refreshes per guild."""
    gid = guild.id
    _guild_pending_vc_updates.setdefault(gid, set()).add(vc_id)

    existing = _guild_vc_flush_tasks.get(gid)
    if existing and not existing.done():
        return

    async def _flush_guild_panels() -> None:
        try:
            await asyncio.sleep(VC_PANEL_UPDATE_DEBOUNCE_SECONDS)
            vc_ids = _guild_pending_vc_updates.pop(gid, set())
            from core.safe_message_edit import CHANNEL_EDIT_MIN_INTERVAL

            for index, vid in enumerate(sorted(vc_ids)):
                if index > 0:
                    await asyncio.sleep(CHANNEL_EDIT_MIN_INTERVAL)
                await update_vc_panel_embed(bot, guild, vid)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            _guild_vc_flush_tasks.pop(gid, None)

    _guild_vc_flush_tasks[gid] = asyncio.create_task(_flush_guild_panels())
