"""Third-party integration polling (Twitch live, etc.)."""
from __future__ import annotations

import logging

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.utils import obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


async def run_twitch_live_cycle(bot: discord.Client) -> None:
    """Check for Twitch streamers going live."""
    if not bot.is_ready():
        return

    # Get Twitch access token
    import os
    from commands.general.twitch import get_twitch_access_token, check_twitch_stream

    access_token = await get_twitch_access_token()
    if not access_token:
        return  # Twitch API not configured

    # Check all guilds with Twitch enabled
    for guild in bot.guilds:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Check if ping_role_id column exists
                try:
                    cur = await db.execute("PRAGMA table_info(twitch_settings)")
                    columns = await cur.fetchall()
                    column_names = [col[1] for col in columns]
                    has_ping_role = "ping_role_id" in column_names
                except Exception:
                    has_ping_role = False
            
                if has_ping_role:
                    cur = await db.execute("""
                        SELECT channel_id, enabled, ping_role_id FROM twitch_settings WHERE guild_id=?
                    """, (guild.id,))
                else:
                    cur = await db.execute("""
                        SELECT channel_id, enabled FROM twitch_settings WHERE guild_id=?
                    """, (guild.id,))
                settings_row = await cur.fetchone()
            
                if not settings_row or not settings_row[1]:
                    continue
            
                channel_id = settings_row[0]
                ping_role_id = settings_row[2] if has_ping_role and len(settings_row) > 2 else None
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
            
                ping_role = guild.get_role(ping_role_id) if ping_role_id else None
            
                # Get streamers for this guild
                cur = await db.execute("""
                    SELECT streamer_name, last_live_status FROM twitch_streamers
                    WHERE guild_id=?
                """, (guild.id,))
                streamers = await cur.fetchall()
            
                for streamer_name, last_status in streamers:
                    stream_data = await check_twitch_stream(streamer_name, access_token)
                    is_live = stream_data is not None
                
                    # Only notify if going from offline to live
                    if is_live and not last_status:
                        # Streamer just went live
                        title = stream_data.get("title", "No title")
                        game = stream_data.get("game_name", "Unknown game")
                        viewer_count = stream_data.get("viewer_count", 0)
                    
                        embed = obsidian_embed(
                            f"🔴 {streamer_name} is now live!",
                            f"**Title:** {title}\n**Game:** {game}\n**Viewers:** {viewer_count}\n\n"
                            f"https://twitch.tv/{streamer_name}",
                            color=discord.Color.purple(),
                            client=bot,
                        )
                    
                        try:
                            # Ping role if configured
                            message_content = ping_role.mention if ping_role else None
                            await channel.send(content=message_content, embed=embed)
                        
                            # Update status
                            await db.execute("""
                                UPDATE twitch_streamers SET last_live_status=1, last_notified_at=?
                                WHERE guild_id=? AND streamer_name=?
                            """, (now_utc().isoformat(), guild.id, streamer_name))
                            await db.commit()
                        except Exception as e:
                            logger.error(f"Error sending Twitch notification: {e}")
                
                    elif not is_live and last_status:
                        # Streamer went offline
                        await db.execute("""
                            UPDATE twitch_streamers SET last_live_status=0
                            WHERE guild_id=? AND streamer_name=?
                        """, (guild.id, streamer_name))
                        await db.commit()

        except Exception as e:
            logger.error(f"Error in twitch_check_loop for guild {guild.id}: {e}", exc_info=True)
