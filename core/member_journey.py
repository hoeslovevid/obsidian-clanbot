"""7-day new-member DM nudge path."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiosqlite
import discord

from core.safe_send import safe_dm
from core.utils import obsidian_embed, EMBED_COLORS
from database import DB_PATH, get_guild_setting, now_utc

logger = logging.getLogger(__name__)

_JOURNEY_DAYS: dict[int, tuple[str, str]] = {
    1: ("👋 Day 1", "Run **`/daily`** and **`/preferences`** (timezone + platform). **`/menu`** has everything else."),
    3: ("🔔 Day 3", "Set Warframe alerts with **`/wfnotify configure`**. Check **`/today`** for your daily snapshot."),
    7: ("📊 Day 7", "Try **`/profile`**, **`/achievements`**, and opt into weekly recap in **`/preferences weekly_recap`**."),
}


async def _ensure_journey_tables() -> None:
    """Create journey tables before any read (loop may run before first member join)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS member_journey_sent (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day_num INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, day_num)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS member_join_log (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.commit()


async def run_member_journey_cycle(bot: discord.Client) -> None:
    """Send day 1/3/7 DMs to eligible members (respects onboarding opt-out)."""
    if not bot.is_ready():
        return
    await _ensure_journey_tables()
    now = now_utc()

    for guild in bot.guilds:
        try:
            enabled = await get_guild_setting(guild.id, "member_journey_enabled")
            if enabled == "0":
                continue
        except Exception:
            pass

        for day_num, (title, body) in _JOURNEY_DAYS.items():
            target_date = (now - timedelta(days=day_num)).date()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT user_id FROM member_join_log
                    WHERE guild_id=? AND date(joined_at)=?
                    """,
                    (guild.id, target_date.isoformat()),
                )
                rows = await cur.fetchall()
            if not rows:
                continue
            for (uid,) in rows:
                member = guild.get_member(int(uid))
                if not member or member.bot:
                    continue
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT 1 FROM member_journey_sent WHERE guild_id=? AND user_id=? AND day_num=?",
                        (guild.id, uid, day_num),
                    )
                    if await cur.fetchone():
                        continue
                try:
                    from core.quiet_hours import in_quiet_hours

                    if await in_quiet_hours(guild.id, uid):
                        continue
                except Exception:
                    pass
                embed = obsidian_embed(title, body, color=EMBED_COLORS["general"], client=bot)
                if await safe_dm(member, embed=embed):
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            """
                            INSERT INTO member_journey_sent (guild_id, user_id, day_num, sent_at)
                            VALUES (?, ?, ?, ?)
                            """,
                            (guild.id, uid, day_num, now.isoformat()),
                        )
                        await db.commit()


async def record_member_join(guild_id: int, user_id: int) -> None:
    """Log join date for journey DMs."""
    await _ensure_journey_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO member_join_log (guild_id, user_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (guild_id, user_id, now_utc().isoformat()),
        )
        await db.commit()
