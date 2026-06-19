"""Giveaway background tasks (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


async def check_ended_giveaways(bot: discord.Client) -> None:
    """Check for ended giveaways and select winners."""
    from commands.giveaways.giveaway_end import end_giveaway

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id FROM giveaways
            WHERE ended = 0 AND datetime(end_time) <= datetime('now')
            """
        )
        ended_giveaways = await cur.fetchall()

    for (giveaway_id,) in ended_giveaways:
        try:
            success, message, winners = await end_giveaway(giveaway_id, bot)
            if success:
                logger.info(
                    "[giveaway] Ended giveaway %s, selected %s winner(s)",
                    giveaway_id,
                    len(winners),
                )
        except Exception as e:
            logger.error("[giveaway] Error ending giveaway %s: %s", giveaway_id, e, exc_info=True)


async def run_giveaway_ending_soon_cycle(bot: discord.Client) -> None:
    """DM entrants ~1 hour before a giveaway ends."""
    try:
        window_start = now_utc() + timedelta(minutes=55)
        window_end = now_utc() + timedelta(minutes=65)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT id, prize, end_time, guild_id FROM giveaways
                WHERE ended=0 AND end_time IS NOT NULL AND end_time != ''
                """
            )
            rows = await cur.fetchall()
        for gid, prize, end_str, guild_id in rows:
            try:
                end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if not (window_start <= end_dt <= window_end):
                continue
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id FROM giveaway_entries WHERE giveaway_id=?",
                    (gid,),
                )
                entrants = [r[0] for r in await cur.fetchall()]
            for uid in entrants:
                user = bot.get_user(uid) or await bot.fetch_user(uid)
                await safe_dm(
                    user,
                    embed=obsidian_embed(
                        "🎁 Giveaway ending soon",
                        f"**{prize}** ends <t:{int(end_dt.timestamp())}:R> — you're entered!",
                        client=bot,
                    ),
                )
    except Exception as e:
        logger.debug("[giveaway] ending-soon loop: %s", e)
