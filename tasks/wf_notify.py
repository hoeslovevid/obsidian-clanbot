"""Warframe notification helpers extracted from tasks/_core.py."""
from __future__ import annotations

import json
import logging

import aiosqlite
import discord

from api.warframe_api import get_baro_status
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)

# Last embed fingerprint per live Baro message — skip redundant PATCH edits
_baro_live_embed_cache: dict[tuple[int, int, int], str] = {}


def get_baro_embed_builder():
    """Lazy import to avoid circular dependency."""
    from commands.warframe.baro import build_baro_embed

    return build_baro_embed


async def warn_broken_notify_channel(
    guild: discord.Guild,
    channel_id: int,
    feature: str,
    *,
    warned: set[tuple[int, int]],
) -> None:
    """DM the guild owner once when a notification channel is missing."""
    key = (guild.id, channel_id)
    if key in warned:
        return
    warned.add(key)
    owner = guild.owner
    if not owner:
        return
    try:
        await owner.send(
            f"⚠️ **{guild.name}** — the **{feature}** notification channel "
            f"(ID: `{channel_id}`) could not be found or is no longer accessible.\n"
            f"Please reconfigure it with the appropriate `/wfnotify` or setup command."
        )
    except Exception:
        pass


async def check_and_notify_baro_arrival(bot, *, warned_channels: set[tuple[int, int]]) -> None:
    """Check if Baro has arrived and send notifications if needed."""
    from api.warframe_api import fetch_baro_data_fresh

    is_active, baro_data = await get_baro_status()

    if not baro_data or not is_active:
        return

    activation = baro_data.get("activation", "")
    if not activation:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM baro_visits WHERE arrival_time=? AND notified=1",
            (activation,),
        )
        if await cur.fetchone():
            return

        cur = await db.execute(
            "SELECT id, notified FROM baro_visits WHERE arrival_time=?",
            (activation,),
        )
        visit = await cur.fetchone()

        visit_id = None
        if visit:
            visit_id, notified = visit
            if notified:
                return
        else:
            inventory_json = json.dumps(baro_data.get("inventory", []))
            await db.execute(
                """
                INSERT INTO baro_visits (arrival_time, departure_time, location, inventory_json, notified, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    activation,
                    baro_data.get("expiry", ""),
                    baro_data.get("location", "Unknown"),
                    inventory_json,
                    now_utc().isoformat(),
                ),
            )
            await db.commit()

            cur = await db.execute(
                "SELECT id FROM baro_visits WHERE arrival_time=?",
                (activation,),
            )
            row = await cur.fetchone()
            visit_id = row[0] if row else None

        fresh_baro_data = await fetch_baro_data_fresh(retries=3, retry_delay=20.0)
        data_to_use = fresh_baro_data if fresh_baro_data else baro_data
        if not (data_to_use.get("inventory") or []):
            logger.debug("Baro active but inventory still empty — skipping arrival notify this cycle")
            return
        if visit_id and data_to_use.get("inventory"):
            await db.execute(
                "UPDATE baro_visits SET inventory_json=?, location=? WHERE id=?",
                (
                    json.dumps(data_to_use["inventory"]),
                    data_to_use.get("location", "Unknown"),
                    visit_id,
                ),
            )
            await db.commit()

    for guild in bot.guilds:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
                    (guild.id,),
                )
                setting = await cur.fetchone()

            if not setting or not setting[1]:
                continue
        except Exception as e:
            logger.error("Error checking baro notification settings for guild %s: %s", guild.id, e)
            continue

        channel_id = setting[0]
        if not channel_id:
            continue

        ch = guild.get_channel(channel_id)
        if not isinstance(ch, discord.TextChannel):
            await warn_broken_notify_channel(
                guild, channel_id, "Baro Ki'Teer", warned=warned_channels
            )
            continue

        build_baro_embed = get_baro_embed_builder()
        embed = build_baro_embed(data_to_use, True, bot)
        embed.title = "🛒 Baro Ki'Teer Has Arrived!"
        embed.color = discord.Color.gold()
        try:
            from core.wf_hub_extras import get_baro_wishlist_overlap

            inv = data_to_use.get("inventory", []) or []
            overlap = await get_baro_wishlist_overlap(guild.id, inv)
            if overlap:
                embed.add_field(name="Clan wishlist", value=overlap, inline=False)
        except Exception:
            pass

        try:
            from core.utils import build_wf_subscriber_ping

            sub_ping = await build_wf_subscriber_ping(guild, "baro")
        except Exception:
            sub_ping = None

        try:
            from core.safe_send import safe_channel_send

            await safe_channel_send(ch, content=sub_ping, embed=embed)

            try:
                from core.wf_hub_extras import dm_baro_wishlist_matches

                inv = data_to_use.get("inventory", []) or []
                await dm_baro_wishlist_matches(
                    bot,
                    guild.id,
                    inv,
                    location=data_to_use.get("location", ""),
                )
            except Exception as wish_exc:
                logger.debug("Baro wishlist DMs skipped for %s: %s", guild.id, wish_exc)

            if visit_id:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE baro_visits SET notified=1 WHERE id=?",
                        (visit_id,),
                    )
                    await db.commit()
        except Exception as e:
            logger.error("Error sending Baro notification to %s: %s", guild.id, e)


def clear_baro_live_embed_cache() -> None:
    _baro_live_embed_cache.clear()


def get_baro_live_embed_cache() -> dict[tuple[int, int, int], str]:
    return _baro_live_embed_cache
