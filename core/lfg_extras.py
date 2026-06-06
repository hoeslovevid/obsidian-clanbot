"""LFG helpers — interest pings, thread summaries, scheduled reminders."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
import discord

from core.embed_templates import embed_template
from core.embed_footers import footer_for
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)

LFG_ROLE_TAGS = (
    "DPS", "Support", "Tank", "Healer", "Steel Path", "Sortie",
    "Archon", "Eidolon", "Index", "Relic", "Voice",
)


async def notify_lfg_interest(
    bot,
    guild: discord.Guild,
    *,
    mission_type: str,
    role_tags: str | None,
    lfg_id: int,
    creator_id: int,
) -> None:
    """DM subscribers whose tags match this LFG post."""
    tags = {t.strip().lower() for t in (role_tags or "").split(",") if t.strip()}
    tags.add(mission_type.strip().lower())
    if not tags:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, tag FROM lfg_interest_subscriptions WHERE guild_id=?",
            (guild.id,),
        )
        rows = await cur.fetchall()
    for user_id, tag in rows:
        if user_id == creator_id:
            continue
        if tag.strip().lower() not in tags:
            continue
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if member:
                await member.send(
                    embed=embed_template(
                        "showcase",
                        "🤝 LFG match",
                        f"A new **{mission_type}** post matches your **{tag}** interest.\n"
                        f"Check the LFG channel in **{guild.name}**.",
                        category="community",
                        footer=footer_for("community_lfg"),
                        client=bot,
                    ),
                )
        except (discord.Forbidden, discord.HTTPException):
            pass


async def build_lfg_thread_summary(
    guild: discord.Guild,
    lfg_id: int,
    *,
    reason: str = "expired",
) -> discord.Embed | None:
    """Brief embed summarizing a closed/expired LFG squad."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT mission_type, creator_id, max_players, description, role_tags, scheduled_at "
            "FROM lfg_posts WHERE id=?",
            (lfg_id,),
        )
        post = await cur.fetchone()
        if not post:
            return None
        mission, creator_id, max_p, desc, tags, sched = post
        cur = await db.execute(
            "SELECT user_id FROM lfg_rsvps WHERE lfg_id=? AND response='JOIN' ORDER BY created_at",
            (lfg_id,),
        )
        rsvps = [r[0] for r in await cur.fetchall()]

    creator = guild.get_member(int(creator_id))
    cname = creator.display_name if creator else f"User {creator_id}"
    squad = ", ".join(
        (guild.get_member(uid).display_name if guild.get_member(uid) else f"User {uid}")
        for uid in rsvps[:8]
    ) or "No RSVPs"
    fields = [
        ("Mission", mission or "—", True),
        ("Host", cname, True),
        ("Squad", squad, False),
    ]
    if tags:
        fields.append(("Tags", tags, True))
    if sched:
        fields.append(("Scheduled", sched, True))
    if desc:
        fields.append(("Notes", desc[:300], False))
    return embed_template(
        "showcase",
        f"📋 LFG Summary ({reason})",
        f"Squad recap for LFG #{lfg_id}",
        category="community",
        fields=fields,
        footer=footer_for("community_lfg"),
        client=None,
    )


async def post_lfg_thread_summary(
    bot,
    guild_id: int,
    lfg_id: int,
    thread_id: int | None,
    *,
    reason: str = "expired",
) -> None:
    guild = bot.get_guild(guild_id)
    if not guild or not thread_id:
        return
    thread = guild.get_thread(thread_id)
    if not isinstance(thread, discord.Thread):
        return
    embed = await build_lfg_thread_summary(guild, lfg_id, reason=reason)
    if embed:
        try:
            await thread.send(embed=embed)
        except discord.HTTPException as e:
            logger.debug("[lfg] thread summary failed: %s", e)
