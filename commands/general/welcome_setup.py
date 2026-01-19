"""Welcome and leave message setup commands."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register welcome/leave setup commands."""
    
    command_decorator = group.command(name="welcome_setup", description="Set up welcome messages (mods only).") if group else bot.tree.command(name="welcome_setup", description="Set up welcome messages (mods only).")
    
    @command_decorator
    @app_commands.describe(
        channel="The channel to send welcome messages to",
        message="Custom welcome message (use {user} for mention, {server} for server name, {member_count} for member count)",
        enabled="Enable or disable welcome messages"
    )
    async def welcome_setup(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        message: Optional[str] = None,
        enabled: Optional[bool] = None
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Get current settings
            cur = await db.execute("""
                SELECT channel_id, message, enabled FROM welcome_settings
                WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
            
            current_channel_id = row[0] if row else None
            current_message = row[1] if row else None
            current_enabled = bool(row[2]) if row and row[2] is not None else True
            
            # Update settings
            new_channel_id = channel.id if channel else current_channel_id
            new_message = message if message is not None else (current_message if current_message else "Welcome to {server}, {user}! You are member #{member_count}.")
            new_enabled = enabled if enabled is not None else current_enabled
            
            await db.execute("""
                INSERT OR REPLACE INTO welcome_settings (guild_id, channel_id, message, enabled)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, new_channel_id, new_message, 1 if new_enabled else 0))
            await db.commit()
        
        # Build response
        status = "enabled" if new_enabled else "disabled"
        channel_mention = f"<#{new_channel_id}>" if new_channel_id else "Not set"
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Welcome Messages Configured",
                f"**Channel:** {channel_mention}\n"
                f"**Status:** {status}\n"
                f"**Message:** {new_message}\n\n"
                f"**Variables:**\n"
                f"• `{{user}}` - User mention\n"
                f"• `{{server}}` - Server name\n"
                f"• `{{member_count}}` - Total member count",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
    
    command_decorator = group.command(name="leave_setup", description="Set up leave messages (mods only).") if group else bot.tree.command(name="leave_setup", description="Set up leave messages (mods only).")
    
    @command_decorator
    @app_commands.describe(
        channel="The channel to send leave messages to",
        message="Custom leave message (use {user} for username, {server} for server name, {member_count} for member count)",
        enabled="Enable or disable leave messages"
    )
    async def leave_setup(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        message: Optional[str] = None,
        enabled: Optional[bool] = None
    ):
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Get current settings
            cur = await db.execute("""
                SELECT channel_id, message, enabled FROM leave_settings
                WHERE guild_id = ?
            """, (interaction.guild.id,))
            row = await cur.fetchone()
            
            current_channel_id = row[0] if row else None
            current_message = row[1] if row else None
            current_enabled = bool(row[2]) if row and row[2] is not None else True
            
            # Update settings
            new_channel_id = channel.id if channel else current_channel_id
            new_message = message if message is not None else (current_message if current_message else "{user} has left {server}. We now have {member_count} members.")
            new_enabled = enabled if enabled is not None else current_enabled
            
            await db.execute("""
                INSERT OR REPLACE INTO leave_settings (guild_id, channel_id, message, enabled)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, new_channel_id, new_message, 1 if new_enabled else 0))
            await db.commit()
        
        # Build response
        status = "enabled" if new_enabled else "disabled"
        channel_mention = f"<#{new_channel_id}>" if new_channel_id else "Not set"
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Leave Messages Configured",
                f"**Channel:** {channel_mention}\n"
                f"**Status:** {status}\n"
                f"**Message:** {new_message}\n\n"
                f"**Variables:**\n"
                f"• `{{user}}` - Username\n"
                f"• `{{server}}` - Server name\n"
                f"• `{{member_count}}` - Total member count",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
