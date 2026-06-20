"""Create a temp squad VC for a full LFG group."""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite
import discord

from core.channels import resolve_temp_vc_category
from core.db import open_db
from core.vc_permissions import build_temp_vc_overwrites, get_vc_staff_roles
from database import DB_PATH, now_utc
from handlers import vc_panel as vc_panel_handlers

logger = logging.getLogger(__name__)


async def create_squad_vc_for_lfg(
    bot: discord.Client,
    guild: discord.Guild,
    lfg_id: int,
    requester: discord.Member,
) -> tuple[bool, str, Optional[discord.VoiceChannel]]:
    """Spin up a join-to-create style VC for LFG members and invite RSVPs."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT creator_id, mission_type, max_players, status
            FROM lfg_posts WHERE id=? AND guild_id=?
            """,
            (lfg_id, guild.id),
        )
        post = await cur.fetchone()
        if not post:
            return False, "LFG post not found.", None
        creator_id, mission, max_players, status = post
        if status != "OPEN":
            return False, "This LFG post is closed.", None
        cur = await db.execute(
            "SELECT user_id FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN' ORDER BY created_at",
            (lfg_id,),
        )
        member_ids = [int(r[0]) for r in await cur.fetchall()]

    if requester.id not in member_ids and requester.id != int(creator_id):
        return False, "Only squad members or the host can open a squad VC.", None

    category = await resolve_temp_vc_category(guild)
    staff_roles = await get_vc_staff_roles(guild)
    overwrites = build_temp_vc_overwrites(
        guild,
        requester,
        category=category,
        staff_roles=staff_roles,
    )
    safe_mission = str(mission or "Squad")[:40]
    vc_name = f"LFG · {safe_mission}"[:100]

    try:
        new_vc = await guild.create_voice_channel(
            name=vc_name,
            category=category,
            overwrites=overwrites,
            reason=f"LFG squad VC for post {lfg_id}",
        )
    except discord.Forbidden:
        return False, "I need **Manage Channels** and **Move Members** to create a squad VC.", None
    except discord.HTTPException as exc:
        return False, f"Couldn't create VC: {exc}", None

    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) "
            "VALUES(?,?,?,?,?)",
            (guild.id, new_vc.id, requester.id, now_utc().isoformat(), now_utc().isoformat()),
        )
        await db.execute(
            "UPDATE lfg_posts SET squad_vc_id=? WHERE id=?",
            (new_vc.id, lfg_id),
        )
        await db.commit()

    try:
        await vc_panel_handlers.post_vc_panel(bot, guild, new_vc, requester)
    except Exception:
        pass

    invited = 0
    for uid in member_ids:
        if uid == requester.id:
            continue
        member = guild.get_member(uid)
        if not member:
            continue
        try:
            from core.safe_send import safe_dm

            await safe_dm(
                member,
                content=f"🎙️ Squad VC ready for **{mission}**: {new_vc.mention}",
            )
            invited += 1
        except Exception:
            pass

    if requester.voice and requester.voice.channel:
        try:
            await requester.move_to(new_vc, reason="LFG squad VC")
        except Exception:
            pass

    return (
        True,
        f"Squad VC {new_vc.mention} created! Notified **{invited}** squad member(s).",
        new_vc,
    )
