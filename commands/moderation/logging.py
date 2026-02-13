"""Logging system setup command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, error_embed, success_embed, is_mod
from database import get_guild_setting, set_guild_setting, DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the logging command."""
    
    command_decorator = group.command(name="logging", description="Configure server logging channels (moderators only).") if group else bot.tree.command(name="logging", description="Configure server logging channels (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        log_type="Type of logs to configure",
        channel="Channel to send logs to"
    )
    @app_commands.choices(log_type=[
        app_commands.Choice(name="Message Deletes", value="message_delete"),
        app_commands.Choice(name="Message Edits", value="message_edit"),
        app_commands.Choice(name="Member Bans", value="member_ban"),
        app_commands.Choice(name="Member Kicks", value="member_kick"),
        app_commands.Choice(name="Member Warnings", value="member_warn"),
        app_commands.Choice(name="Member Joins", value="member_join"),
        app_commands.Choice(name="Member Leaves", value="member_leave"),
        app_commands.Choice(name="Role Changes", value="role_change"),
        app_commands.Choice(name="Channel Updates", value="channel_update"),
        app_commands.Choice(name="Ticket Transcripts", value="ticket_transcript"),
        app_commands.Choice(name="Audit Log", value="audit"),
    ])
    async def logging(
        interaction: discord.Interaction,
        action: str,
        log_type: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure logging channels."""
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
        
        if action.lower() == "setup":
            if not channel:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Channel",
                        "Please specify a channel for logging.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO log_channels (guild_id, log_type, channel_id, enabled)
                    VALUES (?, ?, ?, 1)
                """, (interaction.guild.id, log_type.value, channel.id))
                await db.commit()
            
            log_type_names = {
                "message_delete": "Message Deletes",
                "message_edit": "Message Edits",
                "member_ban": "Member Bans",
                "member_kick": "Member Kicks",
                "member_warn": "Member Warnings",
                "member_join": "Member Joins",
                "member_leave": "Member Leaves",
                "role_change": "Role Changes",
                "channel_update": "Channel Updates",
            }
            
            await interaction.followup.send(
                embed=success_embed(
                    "Logging Configured",
                    f"{log_type_names.get(log_type.value, log_type.value)} will be logged to {channel.mention}.",
                    client=interaction.client,
                ),
                ephemeral=True
            )

        elif action.lower() == "remove":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE log_channels SET enabled=0 
                    WHERE guild_id=? AND log_type=?
                """, (interaction.guild.id, log_type.value))
                await db.commit()
            
            await interaction.followup.send(
                embed=success_embed(
                    "Logging Disabled",
                    f"Logging for {log_type.value} has been disabled.",
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT log_type, channel_id, enabled FROM log_channels
                    WHERE guild_id=? AND enabled=1
                """, (interaction.guild.id,))
                rows = await cur.fetchall()
            
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Logging Status",
                        "No logging channels are configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            desc = ""
            for log_type_val, channel_id, enabled in rows:
                channel = interaction.guild.get_channel(channel_id)
                channel_text = channel.mention if channel else f"Channel ID: {channel_id}"
                desc += f"**{log_type_val}:** {channel_text}\n"
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Logging Status",
                    desc,
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        else:
            await interaction.followup.send(
                embed=error_embed("Invalid Action", "Valid actions: `setup`, `remove`, `status`", client=interaction.client),
                ephemeral=True
            )
