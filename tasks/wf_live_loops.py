"""Warframe live panel updates and API cache warming."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite  # type: ignore
import discord  # type: ignore

from api.warframe_api import get_all_cycles, get_baro_status
from database import DB_PATH, now_utc
from tasks.wf_notify import (
    clear_baro_live_embed_cache,
    get_baro_embed_builder,
    get_baro_live_embed_cache,
)

logger = logging.getLogger(__name__)


async def run_baro_live_update_cycle(bot: discord.Client) -> None:
    """Update live Baro messages with current time remaining."""
    is_active, baro_data = await get_baro_status()

    if not is_active or not baro_data:
        # Baro is not active, clean up all live messages
        clear_baro_live_embed_cache()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM baro_live_messages")
            await db.commit()
        return

    # Get all live messages
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT guild_id, channel_id, message_id, expiry_time
            FROM baro_live_messages
        """)
        messages = await cur.fetchall()

    # Update each message
    for guild_id, channel_id, message_id, expiry_time_str in messages:
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                # Guild not found, remove from database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                        (guild_id, channel_id, message_id)
                    )
                    await db.commit()
                continue
        
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                # Channel not found or wrong type, remove from database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                        (guild_id, channel_id, message_id)
                    )
                    await db.commit()
                continue
        
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                # Message deleted, remove from database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                        (guild_id, channel_id, message_id)
                    )
                    await db.commit()
                continue
        
            # Check if Baro has expired
            try:
                expiry_time = datetime.fromisoformat(expiry_time_str.replace('Z', '+00:00'))
                if expiry_time <= datetime.now(timezone.utc):
                    # Baro has expired, remove from database
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                            (guild_id, channel_id, message_id)
                        )
                        await db.commit()
                    continue
            except Exception:
                pass
        
            # Rebuild embed with updated time
            build_baro_embed = get_baro_embed_builder()
            updated_embed = build_baro_embed(baro_data, True, bot)

            # Skip edit when content unchanged (reduces PATCH spam / 429s)
            desc_key = (updated_embed.description or "") + (updated_embed.title or "")
            cache_key = (guild_id, channel_id, message_id)
            baro_cache = get_baro_live_embed_cache()
            if baro_cache.get(cache_key) == desc_key:
                continue

            from core.safe_message_edit import safe_message_edit

            await safe_message_edit(message, embed=updated_embed)
            baro_cache[cache_key] = desc_key
        
        except discord.Forbidden:
            # Missing permissions, remove from database
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                    (guild_id, channel_id, message_id)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating Baro live message {message_id} in {guild_id}: {e}")
            continue


async def run_cycle_live_update_cycle(bot: discord.Client) -> None:
    """Update pinned live cycle panels in place."""
    if not bot.is_ready():
        return

    from core.cycles_live import (
        build_cycles_live_embed,
        cycles_embed_fingerprint,
        delete_cycle_live_message,
        get_cycle_live_embed_cache,
    )
    from core.safe_message_edit import safe_message_edit

    cycles_data = await get_all_cycles()
    if not cycles_data or not any(cycles_data.values()):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT guild_id, channel_id, message_id
            FROM cycle_live_messages
        """)
        messages = await cur.fetchall()

    cache = get_cycle_live_embed_cache()

    for guild_id, channel_id, message_id in messages:
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                await delete_cycle_live_message(guild_id, channel_id, message_id)
                continue

            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                await delete_cycle_live_message(guild_id, channel_id, message_id)
                continue

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                await delete_cycle_live_message(guild_id, channel_id, message_id)
                continue

            updated_embed = build_cycles_live_embed(bot, cycles_data)
            fp = cycles_embed_fingerprint(updated_embed)
            cache_key = (guild_id, channel_id, message_id)
            if cache.get(cache_key) == fp:
                continue

            await safe_message_edit(message, embed=updated_embed)
            cache[cache_key] = fp

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    UPDATE cycle_live_messages SET updated_at=?
                    WHERE guild_id=? AND channel_id=? AND message_id=?
                    """,
                    (now_utc().isoformat(), guild_id, channel_id, message_id),
                )
                await db.commit()

        except discord.Forbidden:
            await delete_cycle_live_message(guild_id, channel_id, message_id)
        except Exception as e:
            logger.error(
                "Error updating cycle live message %s in %s: %s",
                message_id,
                guild_id,
                e,
            )
            continue


async def run_warframe_cache_warm_cycle(bot: discord.Client) -> None:
    """Keep baro/fissures/alerts/daily_ops cache warm for fast slash commands."""
    if not bot.is_ready():
        return
    from api.warframe_api import warm_hot_warframe_endpoints

    await warm_hot_warframe_endpoints()

