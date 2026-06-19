"""Member count and server stats channel renames."""
from __future__ import annotations

import logging

import aiosqlite  # type: ignore
import discord  # type: ignore

from database import DB_PATH, get_server_stats_channel

logger = logging.getLogger(__name__)


async def run_member_count_update_cycle(bot: discord.Client) -> None:
    """Update member count channel names with accurate counts."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT guild_id, channel_id FROM member_count_channels"
        )
        channels = await cur.fetchall()

    for guild_id, channel_id in channels:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
    
        # Update member count channel
        try:
            channel = guild.get_channel(channel_id)
            if not channel:
                # Channel was deleted, remove from database
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "DELETE FROM member_count_channels WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id)
                    )
                    await db.commit()
                continue
        
            # Get accurate member count
            # guild.member_count is usually accurate, but we can verify by counting
            member_count = guild.member_count
        
            # Count bots and humans from cached members
            # Note: For very large servers, not all members may be cached
            # But guild.member_count should be accurate regardless
            bot_count = sum(1 for member in guild.members if member.bot)
        
            # If we have all members cached, use the cached count
            # Otherwise, estimate based on cached ratio
            if len(guild.members) == member_count:
                # All members cached, accurate count
                human_count = member_count - bot_count
            else:
                # Not all members cached, estimate based on ratio
                if len(guild.members) > 0:
                    bot_ratio = bot_count / len(guild.members)
                    human_count = int(member_count * (1 - bot_ratio))
                else:
                    # Fallback: assume 5% bots (typical Discord server)
                    human_count = int(member_count * 0.95)
                    bot_count = member_count - human_count
        
            # Format channel name using the same refined format
            from commands.general.member_count import format_member_count_name
            name = format_member_count_name(member_count, bot_count, human_count)
        
            # Only update if name changed (to avoid rate limits)
            if channel.name != name:
                await channel.edit(name=name, reason="Member count update")
                logger.debug(f"Updated member count channel {channel_id} in guild {guild_id}: {name}")
        except discord.Forbidden:
            logger.warning(f"No permission to update member count channel {channel_id} in guild {guild_id}")
        except Exception as e:
            logger.error(f"Error updating member count channel {channel_id} in {guild.id}: {e}", exc_info=True)


async def run_server_stats_update_cycle(bot: discord.Client) -> None:
    """Update server stats channel names."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT guild_id FROM server_stats_channels WHERE enabled = 1
        """)
        guilds = await cur.fetchall()

    for (guild_id,) in guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
    
        settings = await get_server_stats_channel(guild_id)
        if not settings or not settings["enabled"]:
            continue
    
        channel = guild.get_channel(settings["channel_id"])
        if not channel:
            # Channel was deleted, disable stats
            from database import remove_server_stats_channel
            await remove_server_stats_channel(guild_id)
            continue
    
        try:
            stats_type = settings["stats_type"]
            new_name = None
        
            if stats_type == "members":
                member_count = guild.member_count
                bot_count = sum(1 for m in guild.members if m.bot)
                human_count = member_count - bot_count
                new_name = f"👥 {member_count:,} Members • 🤖 {bot_count:,} Bots • 👤 {human_count:,} Humans"
        
            elif stats_type == "boosts":
                boost_count = guild.premium_subscription_count or 0
                boost_level = guild.premium_tier
                new_name = f"🚀 {boost_count} Boosts • Level {boost_level}"
        
            elif stats_type == "channels":
                text_channels = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
                voice_channels = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
                total_channels = len(guild.channels)
                new_name = f"💬 {text_channels} Text • 🔊 {voice_channels} Voice • 📊 {total_channels} Total"
        
            elif stats_type == "roles":
                role_count = len(guild.roles)
                new_name = f"🎭 {role_count} Roles"
        
            if new_name and channel.name != new_name:
                # Discord channel name limit is 100 characters
                if len(new_name) > 100:
                    new_name = new_name[:97] + "..."
                await channel.edit(name=new_name)
                logger.info(f"Updated server stats for guild {guild_id}: {new_name}")
    
        except discord.Forbidden:
            logger.warning(f"No permission to edit stats channel in guild {guild_id}")
        except Exception as e:
            logger.error(f"Error updating server stats for guild {guild_id}: {e}", exc_info=True)

