"""Message sniper command - retrieve deleted messages."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite  # type: ignore
import json


def setup(bot, group=None):
    """Register the snipe command."""
    
    command_decorator = group.command(name="snipe", description="View recently deleted messages in this channel.") if group else bot.tree.command(name="snipe", description="View recently deleted messages in this channel.")
    
    @command_decorator
    @app_commands.describe(index="Which deleted message to view (1 = most recent, default: 1)")
    async def snipe(interaction: discord.Interaction, index: int = 1):
        """View deleted messages."""
        if not interaction.guild or not interaction.channel:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check permissions - mods can see all, others can only see their own
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        await interaction.response.defer(ephemeral=True)
        
        if index < 1:
            index = 1
        
        async with aiosqlite.connect(DB_PATH) as db:
            if is_user_mod:
                # Mods can see all deleted messages
                cur = await db.execute("""
                    SELECT content, author_name, author_avatar, attachments, deleted_at
                    FROM deleted_messages
                    WHERE guild_id=? AND channel_id=?
                    ORDER BY deleted_at DESC
                    LIMIT 10 OFFSET ?
                """, (interaction.guild.id, interaction.channel.id, index - 1))
            else:
                # Regular users can only see their own deleted messages
                cur = await db.execute("""
                    SELECT content, author_name, author_avatar, attachments, deleted_at
                    FROM deleted_messages
                    WHERE guild_id=? AND channel_id=? AND user_id=?
                    ORDER BY deleted_at DESC
                    LIMIT 10 OFFSET ?
                """, (interaction.guild.id, interaction.channel.id, interaction.user.id, index - 1))
            
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🔍 No Deleted Messages",
                    f"No deleted messages found{' in this channel' if is_user_mod else ' from you'}.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        content, author_name, author_avatar, attachments_json, deleted_at = row
        
        # Parse attachments
        attachments = []
        if attachments_json:
            try:
                attachments = json.loads(attachments_json)
            except Exception:
                pass
        
        # Build embed
        desc = content or "*No text content*"
        if len(desc) > 2000:
            desc = desc[:1997] + "..."
        
        embed = obsidian_embed(
            f"🔍 Deleted Message #{index}",
            desc,
            color=discord.Color.red(),
            client=interaction.client,
        )
        
        if author_name:
            embed.set_author(name=author_name, icon_url=author_avatar if author_avatar else None)
        
        if attachments:
            embed.add_field(
                name="Attachments",
                value=f"{len(attachments)} attachment(s)",
                inline=False
            )
        
        try:
            deleted_time = datetime.fromisoformat(deleted_at.replace('Z', '+00:00'))
            embed.timestamp = deleted_time
            embed.set_footer(text=f"Deleted at")
        except Exception:
            pass
        
        await interaction.followup.send(embed=embed, ephemeral=True)
