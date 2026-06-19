"""Passive message coins/XP awards (extracted from bot/app.py)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Tuple

import discord  # type: ignore

from core.config import COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS
from core.db import open_db
from database import add_coins, add_xp, get_user_xp, now_utc

logger = logging.getLogger(__name__)

_MESSAGE_COOLDOWN_CACHE: Dict[Tuple[int, int], datetime] = {}
_achievement_definitions_initialized = False


def channel_name_safe(channel: Any) -> str:
    name = getattr(channel, "name", None)
    return str(name) if name else f"<id:{getattr(channel, 'id', '?')}>"


def message_cooldown_active(guild_id: int, user_id: int) -> bool:
    last = _MESSAGE_COOLDOWN_CACHE.get((guild_id, user_id))
    if last is None:
        return False
    return (now_utc() - last).total_seconds() < MESSAGE_COOLDOWN_SECONDS


def message_cooldown_touch(guild_id: int, user_id: int) -> None:
    _MESSAGE_COOLDOWN_CACHE[(guild_id, user_id)] = now_utc()


async def award_message_economy(message: discord.Message) -> None:
    """Award passive coins/XP for a qualifying message (cooldown-gated)."""
    if not message.guild:
        return

    if message_cooldown_active(message.guild.id, message.author.id):
        return

    async with open_db() as db:
        cur = await db.execute(
            "SELECT last_message_at FROM message_cooldowns WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()

        if row:
            last_message_at = datetime.fromisoformat(row[0])
            time_since = (now_utc() - last_message_at).total_seconds()
            if time_since < MESSAGE_COOLDOWN_SECONDS:
                message_cooldown_touch(message.guild.id, message.author.id)
                return

        now_iso = now_utc().isoformat()
        await db.execute(
            """
            INSERT INTO message_cooldowns (guild_id, user_id, last_message_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET last_message_at=?
            """,
            (message.guild.id, message.author.id, now_iso, now_iso),
        )
        await db.commit()

    message_cooldown_touch(message.guild.id, message.author.id)

    from core.utils import get_active_multiplier

    coins_mult = await get_active_multiplier(message.guild.id, "coins")
    await add_coins(
        message.guild.id,
        message.author.id,
        max(1, int(round(COINS_PER_MESSAGE * coins_mult))),
        "MESSAGE",
        f"Message in #{channel_name_safe(message.channel)}",
    )

    from core.utils import XP_ENABLED, XP_PER_MESSAGE

    if not XP_ENABLED:
        return

    xp_mult = await get_active_multiplier(message.guild.id, "xp")
    leveled_up = await add_xp(
        message.guild.id,
        message.author.id,
        max(1, int(round(XP_PER_MESSAGE * xp_mult))),
        "MESSAGE",
    )
    if leveled_up and isinstance(message.author, discord.Member):
        xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
        logger.info(
            "User %s leveled up to level %s in guild %s",
            message.author.id,
            level,
            message.guild.id,
        )
        from core.utils import send_levelup_announcement

        await send_levelup_announcement(message.guild, message.author, level, xp, total_xp)

        from database import get_all_level_roles_up_to

        level_roles = await get_all_level_roles_up_to(message.guild.id, level)
        if level_roles:
            roles_to_add = []
            for lr in level_roles:
                role = message.guild.get_role(lr["role_id"])
                if role and role not in message.author.roles:
                    roles_to_add.append(role)
            if roles_to_add:
                try:
                    await message.author.add_roles(
                        *roles_to_add, reason=f"Leveled up to level {level}"
                    )
                    logger.info(
                        "Assigned level roles to %s: %s",
                        message.author.id,
                        [r.id for r in roles_to_add],
                    )
                except Exception as e:
                    logger.error("Error assigning level roles: %s", e)

    xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
    from database import check_and_record_milestone, check_and_unlock_achievement

    global _achievement_definitions_initialized
    if not _achievement_definitions_initialized:
        from database import (
            initialize_achievement_definitions,
            initialize_badge_definitions,
            initialize_title_definitions,
        )

        await initialize_achievement_definitions()
        await initialize_badge_definitions()
        await initialize_title_definitions()
        _achievement_definitions_initialized = True

    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT messages_sent FROM activity_stats
            WHERE guild_id=? AND user_id=?
            """,
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()
        message_count = row[0] if row else 0
        await db.execute(
            """
            INSERT INTO activity_stats (guild_id, user_id, messages_sent, last_activity_date)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                messages_sent = messages_sent + 1,
                last_activity_date = excluded.last_activity_date
            """,
            (message.guild.id, message.author.id, now_utc().isoformat()),
        )
        await db.commit()

    new_message_count = message_count + 1
    client = message.client

    for milestone_level in (10, 25, 50, 100):
        if level >= milestone_level:
            milestone_achieved = await check_and_record_milestone(
                message.guild.id, message.author.id, "level", milestone_level
            )
            if milestone_achieved:
                await check_and_unlock_achievement(
                    message.guild.id,
                    message.author.id,
                    f"level_{milestone_level}",
                    client,
                )

    achievement_map = {
        1: "first_message",
        100: "hundred_messages",
        1000: "thousand_messages",
        10000: "ten_thousand_messages",
    }
    for milestone_count in (1, 100, 1000, 10000):
        if new_message_count >= milestone_count:
            milestone_achieved = await check_and_record_milestone(
                message.guild.id, message.author.id, "message_count", milestone_count
            )
            if milestone_achieved and milestone_count in achievement_map:
                await check_and_unlock_achievement(
                    message.guild.id,
                    message.author.id,
                    achievement_map[milestone_count],
                    client,
                )
