"""Starboard and reaction-role handlers (extracted from bot/app.py)."""
from __future__ import annotations

import logging
from typing import Any

import discord  # type: ignore

from core.db import open_db
from core.utils import obsidian_embed

logger = logging.getLogger(__name__)


def channel_mention_safe(channel: Any) -> str:
    if hasattr(channel, "mention"):
        return channel.mention
    return "#unknown-channel"


async def handle_raw_reaction_add(bot: discord.Client, payload: discord.RawReactionActionEvent) -> None:
    """Handle reaction adds for starboard and other features."""
    # Starboard handling — read DB first, then do all network I/O with connection closed
    if payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
        if guild:
            # Phase 1: read-only DB fetch (connection opened and closed quickly)
            async with open_db() as db:
                cur = await db.execute(
                    "SELECT channel_id, threshold, emoji FROM starboard_settings WHERE guild_id=?",
                    (guild.id,),
                )
                sb_row = await cur.fetchone()

            if sb_row:
                starboard_channel_id, threshold, emoji = sb_row
                starboard_channel = guild.get_channel(starboard_channel_id)

                if isinstance(starboard_channel, discord.TextChannel) and str(payload.emoji) == emoji:
                    try:
                        channel = guild.get_channel(payload.channel_id)
                        if channel and isinstance(channel, discord.TextChannel):
                            # Network I/O — connection is already closed above
                            message = await channel.fetch_message(payload.message_id)
                            reaction = discord.utils.get(message.reactions, emoji=emoji)

                            if reaction and reaction.count >= threshold:
                                # Phase 2: check existing starboard entry (brief connection)
                                async with open_db() as db:
                                    cur = await db.execute("""
                                        SELECT starboard_message_id, stars FROM starboard_messages
                                        WHERE guild_id=? AND original_message_id=?
                                    """, (guild.id, message.id))
                                    existing = await cur.fetchone()

                                if existing:
                                    starboard_msg_id, old_stars = existing
                                    if reaction.count != old_stars:
                                        try:
                                            # Network I/O
                                            starboard_msg = await starboard_channel.fetch_message(starboard_msg_id)
                                            embed = starboard_msg.embeds[0] if starboard_msg.embeds else None
                                            if embed:
                                                embed.set_footer(text=f"{reaction.count} {emoji} | {channel_mention_safe(message.channel)}")
                                                await starboard_msg.edit(embed=embed)
                                            # Phase 3: write (separate short connection)
                                            async with open_db() as db:
                                                await db.execute("""
                                                    UPDATE starboard_messages SET stars=?
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (reaction.count, guild.id, message.id))
                                                await db.commit()
                                        except discord.NotFound:
                                            async with open_db() as db:
                                                await db.execute("""
                                                    DELETE FROM starboard_messages
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (guild.id, message.id))
                                                await db.commit()
                                else:
                                    # Build and send new starboard embed (network I/O)
                                    embed = obsidian_embed(
                                        f"{emoji} {message.author.display_name}",
                                        message.content or "*No content*",
                                        color=discord.Color.gold(),
                                        client=bot,
                                    )
                                    embed.set_footer(text=f"{reaction.count} {emoji} | {channel_mention_safe(message.channel)}")
                                    embed.timestamp = message.created_at
                                    if message.attachments:
                                        embed.set_image(url=message.attachments[0].url)
                                    starboard_msg = await starboard_channel.send(embed=embed)
                                    # Phase 3: write result
                                    async with open_db() as db:
                                        await db.execute("""
                                            INSERT INTO starboard_messages (guild_id, original_message_id, starboard_message_id, stars)
                                            VALUES (?, ?, ?, ?)
                                        """, (guild.id, message.id, starboard_msg.id, reaction.count))
                                        await db.commit()
                    except Exception as e:
                        logger.error(f"Error handling starboard reaction: {e}", exc_info=True)
    
    # Reaction role handling (guild DMs have no guild_id)
    gid_react = payload.guild_id
    if gid_react is None:
        return
    if payload.member and payload.member.bot:
        return

    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (gid_react, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(gid_react)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    # Get member (might be None if user left)
    member = payload.member
    if not member:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
    
    # Check bot permissions
    if not guild.me.guild_permissions.manage_roles:
        return
    
    # Check if bot's role is high enough
    if guild.me.top_role <= role:
        return
    
    # Add role
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Reaction role")
            logger.info(f"[reaction_role] Added role {role.name} to {member} via reaction {payload.emoji}")
            
            # Send temporary confirmation message in channel (auto-deletes after 3 seconds)
            channel = guild.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    confirm_msg = await channel.send(
                        f"{member.mention} You have added {role.mention}!",
                        delete_after=3.0  # Delete after 3 seconds
                    )
                except discord.Forbidden:
                    # Can't send messages, that's okay
                    pass
                except Exception as e:
                    logger.debug(f"[reaction_role] Could not send confirmation message: {e}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to add role {role.name} to {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error adding role: {e}")




async def handle_raw_reaction_remove(bot: discord.Client, payload: discord.RawReactionActionEvent) -> None:
    """Handle reaction role removal."""
    gid_rm = payload.guild_id
    if gid_rm is None:
        return

    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (gid_rm, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(gid_rm)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    # Get member
    try:
        member = await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return
    
    # Check bot permissions
    if not guild.me.guild_permissions.manage_roles:
        return
    
    # Check if bot's role is high enough
    if guild.me.top_role <= role:
        return
    
    # Remove role
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role removed")
            logger.info(f"[reaction_role] Removed role {role.name} from {member} via reaction removal {payload.emoji}")
            
            # Send temporary confirmation message in channel (auto-deletes after 3 seconds)
            channel = guild.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    confirm_msg = await channel.send(
                        f"{member.mention} You have removed {role.mention}!",
                        delete_after=3.0  # Delete after 3 seconds
                    )
                except discord.Forbidden:
                    # Can't send messages, that's okay
                    pass
                except Exception as e:
                    logger.debug(f"[reaction_role] Could not send confirmation message: {e}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to remove role {role.name} from {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error removing role: {e}")


