"""Warframe Market price-watch storage and checks."""
from __future__ import annotations

import logging

import aiosqlite
import discord

from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


async def ensure_price_watch_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS price_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                max_price INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'pc',
                created_at TEXT NOT NULL,
                last_notified_at TEXT
            )
            """
        )
        await db.commit()


async def add_watch(
    guild_id: int,
    user_id: int,
    item_name: str,
    max_price: int,
    platform: str = "pc",
) -> tuple[bool, str]:
    await ensure_price_watch_table()
    name = item_name.strip()[:120]
    if not name or max_price < 1:
        return False, "Item name and a positive max price are required."
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM price_watches WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        count = int((await cur.fetchone())[0] or 0)
        if count >= 10:
            return False, "You can watch up to **10** items. Remove one with `/price_unwatch` first."
        await db.execute(
            "INSERT INTO price_watches (guild_id, user_id, item_name, max_price, platform, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, name, max_price, platform.lower(), now_utc().isoformat()),
        )
        await db.commit()
    return True, f"Watching **{name}** — I'll DM you when sell orders are **≤ {max_price}p**."


async def remove_watch(guild_id: int, user_id: int, item_name: str) -> tuple[bool, str]:
    await ensure_price_watch_table()
    name = item_name.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM price_watches WHERE guild_id=? AND user_id=? AND lower(item_name)=lower(?)",
            (guild_id, user_id, name),
        )
        await db.commit()
        if cur.rowcount:
            return True, f"Stopped watching **{name}**."
    return False, f"No watch found for **{name}**."


async def list_watches(guild_id: int, user_id: int) -> list[tuple[str, int, str]]:
    await ensure_price_watch_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT item_name, max_price, platform FROM price_watches "
            "WHERE guild_id=? AND user_id=? ORDER BY id",
            (guild_id, user_id),
        )
        return [(str(r[0]), int(r[1]), str(r[2])) for r in await cur.fetchall()]


async def digest_market_line(guild_id: int, user_id: int) -> str | None:
    """One-line summary of active watches for the daily digest."""
    rows = await list_watches(guild_id, user_id)
    if not rows:
        return None
    parts = [f"**{name}** ≤{price}p" for name, price, _ in rows[:4]]
    extra = f" +{len(rows) - 4} more" if len(rows) > 4 else ""
    return f"💎 **Price watches** ({len(rows)}) — " + ", ".join(parts) + extra


async def check_price_watches(bot) -> None:
    """DM users when watched items drop to their target price."""
    await ensure_price_watch_table()
    from api.warframe_api import get_warframe_market_price, search_warframe_market_item
    from core.quiet_hours import in_quiet_hours
    from core.command_mentions import command_mention
    from views.price_watch_unwatch import PriceWatchUnwatchView

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, guild_id, user_id, item_name, max_price, platform, last_notified_at "
            "FROM price_watches"
        )
        rows = await cur.fetchall()

    trade_price = command_mention("trading trade_price", fallback="`/trading trade_price`")

    for row_id, guild_id, user_id, item_name, max_price, platform, last_notified in rows:
        try:
            if await in_quiet_hours(int(guild_id), int(user_id)):
                continue
            item = await search_warframe_market_item(item_name, platform)
            if not item:
                continue
            price_data = await get_warframe_market_price(item.get("url_name", ""), platform)
            if not price_data:
                continue
            lowest = price_data.get("lowest_sell")
            if lowest is None or int(lowest) > int(max_price):
                continue
            today = now_utc().date().isoformat()
            if last_notified and str(last_notified)[:10] == today:
                continue
            user = bot.get_user(int(user_id))
            if not user:
                try:
                    user = await bot.fetch_user(int(user_id))
                except Exception:
                    continue
            embed = discord.Embed(
                title="💎 Price watch triggered",
                description=(
                    f"**{item_name}** has sellers at **{lowest}p** "
                    f"(your target: ≤{max_price}p on {platform.upper()}).\n\n"
                    f"Check {trade_price} for details."
                ),
                color=discord.Color.gold(),
            )
            view = PriceWatchUnwatchView(int(guild_id), int(user_id), item_name)
            from core.dm_coalesce import queue_coalesced_dm

            await queue_coalesced_dm(
                bot,
                int(guild_id),
                int(user_id),
                "Price watch",
                embed,
                view=view,
            )
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE price_watches SET last_notified_at=? WHERE id=?",
                    (now_utc().isoformat(), row_id),
                )
                await db.commit()
        except Exception as exc:
            logger.debug("[price_watch] row %s: %s", row_id, exc)
