"""Alert notification setup command."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting, DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the alerts_notify command."""
    
    command_decorator = group.command(name="alerts_notify", description="Configure alert notifications (moderators only).") if group else bot.tree.command(name="alerts_notify", description="Configure alert notifications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to send alert notifications to"
    )
    async def alerts_notify(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure alert notifications."""
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
                        "Please specify a channel for alert notifications.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_guild_setting(interaction.guild.id, "alerts_channel_id", str(channel.id))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Alert Notifications Configured",
                    f"Alert notifications will be sent to {channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            await set_guild_setting(interaction.guild.id, "alerts_channel_id", "")
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Alert Notifications Disabled",
                    "Alert notifications have been disabled.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            channel_id_str = await get_guild_setting(interaction.guild.id, "alerts_channel_id")
            
            if not channel_id_str:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📢 Alert Notifications Status",
                        "Alert notifications are not configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            try:
                channel_id = int(channel_id_str)
                channel_obj = interaction.guild.get_channel(channel_id)
                if channel_obj:
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "📢 Alert Notifications Status",
                            f"**Channel:** {channel_obj.mention}\n**Status:** Enabled",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "📢 Alert Notifications Status",
                            f"**Channel ID:** {channel_id}\n**Status:** Channel not found (may have been deleted)",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
            except ValueError:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📢 Alert Notifications Status",
                        "Alert notifications are configured but channel ID is invalid.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `setup`, `remove`, `status`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
