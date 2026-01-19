"""Starboard system commands."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register starboard commands."""
    
    command_decorator = group.command(name="starboard_setup", description="Configure starboard (moderators only).") if group else bot.tree.command(name="starboard_setup", description="Configure starboard (moderators only).")
    
    @command_decorator
    @app_commands.describe(channel="Channel to post starred messages", threshold="Number of reactions needed (default: 5)", emoji="Emoji to use for starboard (default: ⭐)")
    async def starboard_setup(interaction: discord.Interaction, channel: discord.TextChannel, threshold: Optional[int] = 5, emoji: Optional[str] = "⭐"):
        """Configure starboard."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if threshold < 1:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Threshold",
                    "Threshold must be at least 1.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO starboard_settings (guild_id, channel_id, threshold, emoji)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, channel.id, threshold, emoji))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Starboard Configured",
                f"**Channel:** {channel.mention}\n**Threshold:** {threshold} {emoji}\n**Emoji:** {emoji}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="starboard_status", description="View starboard settings.") if group else bot.tree.command(name="starboard_status", description="View starboard settings.")
    
    @command_decorator
    async def starboard_status(interaction: discord.Interaction):
        """View starboard settings."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT channel_id, threshold, emoji FROM starboard_settings WHERE guild_id=?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📌 Starboard",
                    "Starboard is not configured. Use `/starboard_setup` to configure it.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        channel_id, threshold, emoji = row
        channel = interaction.guild.get_channel(channel_id)
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "📌 Starboard Settings",
                f"**Channel:** {channel.mention if channel else f'Channel ID: {channel_id}'}\n**Threshold:** {threshold} {emoji}\n**Emoji:** {emoji}",
                color=discord.Color.blue(),
                client=interaction.client,
            ),
            ephemeral=True
        )
