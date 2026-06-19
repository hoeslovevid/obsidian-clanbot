"""Warframe devstream + forum RSS notification loops."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore

from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def run_devstream_notify_cycle(bot: discord.Client) -> None:
    """Check for upcoming devstreams and send notifications."""
    if not bot.is_ready():
        return

    # Check all guilds that have devstream notifications enabled
    for guild in bot.guilds:
        try:
            # Check if devstream notifications are enabled (using guild_settings table).
            # Canonical key is devstream_notify_channel_id; fall back to
            # the legacy devstream_channel_id for guilds whose migration
            # hasn't run yet.
            from database import get_guild_setting, set_guild_setting
            channel_id_str = await get_guild_setting(guild.id, "devstream_notify_channel_id")
            if not channel_id_str:
                channel_id_str = await get_guild_setting(guild.id, "devstream_channel_id")
            next_devstream_date_str = await get_guild_setting(guild.id, "next_devstream_date")
        
            if not channel_id_str or not channel_id_str.isdigit():
                continue  # Not configured or disabled
        
            channel_id = int(channel_id_str)
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
        
            # Auto-detect next devstream date if not set or if current date is in the past
            now = now_utc()
            devstream_date = None
        
            if next_devstream_date_str:
                try:
                    devstream_date = dateparser.parse(next_devstream_date_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if devstream_date and devstream_date < now:
                        # Devstream date is in the past, calculate next one
                        devstream_date = None
                except Exception:
                    devstream_date = None
        
            # If no valid devstream date, auto-calculate the next one
            if not devstream_date:
                from api.warframe_api import calculate_next_devstream_date
                devstream_date = await calculate_next_devstream_date()
            
                if devstream_date:
                    # Store the auto-detected date
                    await set_guild_setting(guild.id, "next_devstream_date", devstream_date.isoformat())
                    next_devstream_date_str = devstream_date.isoformat()
                    logger.info(f"[devstream] Auto-detected next devstream for guild {guild.id}: {devstream_date.isoformat()}")
                else:
                    # Couldn't calculate, skip this guild
                    continue
        
            time_until = (devstream_date - now).total_seconds()
        
            # Check if devstream is within 24 hours and we haven't sent a 24h notification
            if timedelta(hours=23) < timedelta(seconds=time_until) <= timedelta(hours=25):
                async with aiosqlite.connect(DB_PATH) as db:
                    # Check if 24h notification was sent
                    cur = await db.execute("""
                        SELECT 1 FROM devstream_notifications_sent 
                        WHERE guild_id=? AND devstream_date=? AND notification_type='24h'
                    """, (guild.id, next_devstream_date_str))
                    if not await cur.fetchone():
                        # Send 24h notification
                        embed = obsidian_embed(
                            "≡ƒô║ Devstream Reminder",
                            f"**Warframe Devstream** starts in **24 hours**!\n\n"
                            f"**Date:** <t:{int(devstream_date.timestamp())}:F>",
                            color=discord.Color.blue(),
                            client=bot,
                        )
                        try:
                            await channel.send(embed=embed)
                            await db.execute("""
                                INSERT INTO devstream_notifications_sent 
                                (guild_id, devstream_date, notification_type, notified_at)
                                VALUES (?, ?, '24h', ?)
                            """, (guild.id, next_devstream_date_str, now.isoformat()))
                            await db.commit()
                        except Exception as e:
                            logger.error(f"Error sending devstream 24h notification to guild {guild.id}: {e}")
        
            # Check if devstream is within 1 hour and we haven't sent a 1h notification
            elif timedelta(minutes=55) < timedelta(seconds=time_until) <= timedelta(hours=1, minutes=5):
                async with aiosqlite.connect(DB_PATH) as db:
                    # Check if 1h notification was sent
                    cur = await db.execute("""
                        SELECT 1 FROM devstream_notifications_sent 
                        WHERE guild_id=? AND devstream_date=? AND notification_type='1h'
                    """, (guild.id, next_devstream_date_str))
                    if not await cur.fetchone():
                        # Send 1h notification
                        embed = obsidian_embed(
                            "≡ƒô║ Devstream Starting Soon!",
                            f"**Warframe Devstream** starts in **1 hour**!\n\n"
                            f"**Date:** <t:{int(devstream_date.timestamp())}:F>",
                            color=discord.Color.green(),
                            client=bot,
                        )
                        try:
                            await channel.send(embed=embed)
                            await db.execute("""
                                INSERT INTO devstream_notifications_sent 
                                (guild_id, devstream_date, notification_type, notified_at)
                                VALUES (?, ?, '1h', ?)
                            """, (guild.id, next_devstream_date_str, now.isoformat()))
                            await db.commit()
                        except Exception as e:
                            logger.error(f"Error sending devstream 1h notification to guild {guild.id}: {e}")
    
        except Exception as e:
            logger.error(f"Error in devstream_check_loop for guild {guild.id}: {e}", exc_info=True)


async def run_forum_feed_cycle(bot: discord.Client) -> None:
    """Check Warframe forums RSS for new posts."""
    if not bot.is_ready():
        return
    import aiohttp
    import xml.etree.ElementTree as ET
    url = "https://forums.warframe.com/latest.rss"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return
                text = await r.text()
        except Exception:
            return
    root = ET.fromstring(text)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    seen = set()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT item_id FROM integration_seen WHERE source='forum'")
        for row in await cur.fetchall():
            seen.add(row[0])
    for item in items[:5]:
        link = None
        title = None
        guid = None
        for child in item:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "link":
                link = child.text or child.get("href", "")
            elif tag == "title":
                title = (child.text or "").strip()
            elif tag in ("id", "guid"):
                guid = (child.text or "").strip()
        for link_el in item.findall(".//{http://www.w3.org/2005/Atom}link"):
            if not link:
                link = link_el.get("href", "")
        if not guid:
            guid = link or (title or "")[:200] or ""
        if not guid or guid in seen:
            continue
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO integration_seen (source, item_id, created_at) VALUES ('forum', ?, ?)",
                (guid[:500], now_utc().isoformat()),
            )
            await db.commit()
        for guild in bot.guilds:
            ch_id = await get_guild_setting(guild.id, "forum_notify_channel_id")
            if not ch_id:
                continue
            ch = guild.get_channel(int(ch_id))
            if not isinstance(ch, discord.TextChannel):
                continue
            try:
                await ch.send(
                    embed=obsidian_embed(
                        "New Forum Post",
                        f"**{title or 'New post'}**\n\n{link or ''}",
                        color=discord.Color.blue(),
                        client=bot,
                    ),
                )
            except Exception as e:
                logger.warning(f"[forum] Error notifying guild {guild.id}: {e}")

async def run_youtube_feed_cycle(bot: discord.Client) -> None:
    """Check Warframe YouTube channel RSS for new videos."""
    if not bot.is_ready():
        return
    import aiohttp
    import xml.etree.ElementTree as ET
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id=UCZ8h7R8l2LoXzbc-GufOyKw"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return
                text = await r.text()
        except Exception:
            return
    root = ET.fromstring(text)
    ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    seen = set()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT item_id FROM integration_seen WHERE source='youtube'")
        for row in await cur.fetchall():
            seen.add(row[0])
    for entry in entries[:3]:
        vid_id = None
        title = None
        link = None
        vid_el = entry.find("{http://www.youtube.com/xml/schemas/2015}videoId")
        if vid_el is not None and vid_el.text:
            vid_id = vid_el.text.strip()
        tit_el = entry.find("{http://www.w3.org/2005/Atom}title")
        if tit_el is not None and tit_el.text:
            title = tit_el.text.strip()
        for link_el in entry.findall("{http://www.w3.org/2005/Atom}link"):
            if link_el.get("rel") == "alternate":
                link = link_el.get("href", "")
                break
        if not vid_id and link:
            if "v=" in link:
                vid_id = link.split("v=")[-1].split("&")[0]
        if not link and vid_id:
            link = f"https://www.youtube.com/watch?v={vid_id}"
        if not vid_id:
            vid_id = link or title or ""
        if not vid_id or vid_id in seen:
            continue
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO integration_seen (source, item_id, created_at) VALUES ('youtube', ?, ?)",
                (vid_id[:500], now_utc().isoformat()),
            )
            await db.commit()
        for guild in bot.guilds:
            ch_id = await get_guild_setting(guild.id, "youtube_notify_channel_id")
            if not ch_id:
                continue
            ch = guild.get_channel(int(ch_id))
            if not isinstance(ch, discord.TextChannel):
                continue
            try:
                await ch.send(
                    embed=obsidian_embed(
                        "New Warframe Video",
                        f"**{title or 'New upload'}**\n\n{link or ''}",
                        color=discord.Color.red(),
                        client=bot,
                    ),
                )
            except Exception as e:
                logger.warning(f"[youtube] Error notifying guild {guild.id}: {e}")

