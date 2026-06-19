"""Message delete/edit logging (extracted from bot/app.py)."""
from __future__ import annotations

import json
import logging
from typing import Any

import discord  # type: ignore

from core.db import open_db
from core.utils import obsidian_embed
from database import now_utc

logger = logging.getLogger(__name__)


def channel_mention_safe(channel: Any) -> str:
    if hasattr(channel, "mention"):
        return channel.mention
    return "#unknown-channel"


async def handle_message_delete(bot: discord.Client, message: discord.Message) -> None:
    """Log deleted messages."""
    if not message.guild or message.author.bot:
        return
    
    # Store deleted message and check log channel in single transaction
    attachments_json = None
    if message.attachments:
        attachments_json = json.dumps([{"url": att.url, "filename": att.filename} for att in message.attachments])
    
    embeds_json = None
    if message.embeds:
        embeds_json = json.dumps([embed.to_dict() for embed in message.embeds])
    
    async with open_db() as db:
        # Store deleted message
        await db.execute("""
            INSERT OR REPLACE INTO deleted_messages 
            (guild_id, channel_id, message_id, user_id, content, author_name, author_avatar, attachments, embeds, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.guild.id,
            message.channel.id,
            message.id,
            message.author.id,
            message.content[:2000] if message.content else None,
            str(message.author),
            str(message.author.display_avatar.url) if message.author.display_avatar else None,
            attachments_json,
            embeds_json,
            now_utc().isoformat()
        ))
        
        # Check log channel in same transaction
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_delete' AND enabled=1
        """, (message.guild.id,))
        row = await cur.fetchone()
        await db.commit()
    
    if row:
        log_channel = message.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "🗑️ Message Deleted",
                    f"**Channel:** {channel_mention_safe(message.channel)}\n"
                    f"**Author:** {message.author.mention} ({message.author})\n"
                    f"**Content:** {message.content[:1000] if message.content else '*No content*'}",
                    color=discord.Color.red(),
                    client=bot,
                )
                if message.attachments:
                    embed.add_field(name="Attachments", value=f"{len(message.attachments)} attachment(s)", inline=False)
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging message delete: {e}")




async def handle_message_edit(bot: discord.Client, before: discord.Message, after: discord.Message) -> None:
    """Log edited messages."""
    if not after.guild or after.author.bot or before.content == after.content:
        return
    
    # Store edit and check log channel in single transaction
    async with open_db() as db:
        # Store edit
        await db.execute("""
            INSERT INTO edited_messages 
            (guild_id, channel_id, message_id, user_id, old_content, new_content, author_name, edited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            after.guild.id,
            after.channel.id,
            after.id,
            after.author.id,
            before.content[:2000] if before.content else None,
            after.content[:2000] if after.content else None,
            str(after.author),
            now_utc().isoformat()
        ))
        
        # Check log channel in same transaction
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_edit' AND enabled=1
        """, (after.guild.id,))
        row = await cur.fetchone()
        await db.commit()
    
    if row:
        log_channel = after.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "✏️ Message Edited",
                    f"**Channel:** {channel_mention_safe(after.channel)}\n"
                    f"**Author:** {after.author.mention} ({after.author})\n"
                    f"**Before:** {before.content[:500] if before.content else '*No content*'}\n"
                    f"**After:** {after.content[:500] if after.content else '*No content*'}\n"
                    f"[Jump to Message]({after.jump_url})",
                    color=discord.Color.orange(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging message edit: {e}")


async def handle_member_ban(bot: discord.Client, guild: discord.Guild, user: discord.User) -> None:
    """Log member bans."""
    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='member_ban' AND enabled=1
            """,
            (guild.id,),
        )
        row = await cur.fetchone()

    if row:
        log_channel = guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                reason = "No reason provided"
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                    if entry.target and entry.target.id == user.id:
                        reason = entry.reason or "No reason provided"
                        break

                embed = obsidian_embed(
                    "🔨 Member Banned",
                    f"**User:** {user.mention} ({user})\n"
                    f"**User ID:** {user.id}\n"
                    f"**Reason:** {reason}",
                    color=discord.Color.red(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging member ban: {e}")


async def handle_member_update(bot: discord.Client, before: discord.Member, after: discord.Member) -> None:
    """Log role changes."""
    if before.roles == after.roles:
        return

    added_roles = [r for r in after.roles if r not in before.roles]
    removed_roles = [r for r in before.roles if r not in after.roles]

    if not added_roles and not removed_roles:
        return

    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='role_change' AND enabled=1
            """,
            (after.guild.id,),
        )
        row = await cur.fetchone()

    if row:
        log_channel = after.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                desc = f"**User:** {after.mention} ({after})\n"
                if added_roles:
                    desc += f"**Added Roles:** {', '.join([r.mention for r in added_roles if r != after.guild.default_role])}\n"
                if removed_roles:
                    desc += f"**Removed Roles:** {', '.join([r.mention for r in removed_roles if r != after.guild.default_role])}\n"

                embed = obsidian_embed(
                    "🎭 Role Updated",
                    desc,
                    color=discord.Color.blue(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging role change: {e}")

