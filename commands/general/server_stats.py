"""Server stats channel command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import set_server_stats_channel, remove_server_stats_channel, get_server_stats_channel


def setup(bot):
    """Register the server_stats command."""
    
    @bot.tree.command(name="server_stats", description="Configure the server stats channel (mods only).")
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to display stats in",
        stats_type="Type of stats to display"
    )
    @app_commands.choices(stats_type=[
        app_commands.Choice(name="Members", value="members"),
        app_commands.Choice(name="Boosts", value="boosts"),
        app_commands.Choice(name="Channels", value="channels"),
        app_commands.Choice(name="Roles", value="roles"),
    ])
    async def server_stats(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None,
        stats_type: Optional[app_commands.Choice[str]] = None
    ):
        """Configure server stats channel."""
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
                        "Please specify a channel for server stats.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            stats_type_val = stats_type.value if stats_type else "members"
            await set_server_stats_channel(interaction.guild.id, channel.id, stats_type_val)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Server Stats Configured",
                    f"Server stats will be displayed in {channel.mention}.\nType: **{stats_type_val.title()}**",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            await remove_server_stats_channel(interaction.guild.id)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Server Stats Disabled",
                    "Server stats channel has been disabled.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            settings = await get_server_stats_channel(interaction.guild.id)
            
            if not settings:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📊 Server Stats Status",
                        "Server stats are not configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            channel_obj = interaction.guild.get_channel(settings["channel_id"])
            channel_text = channel_obj.mention if channel_obj else f"Channel ID: {settings['channel_id']}"
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📊 Server Stats Status",
                    f"**Channel:** {channel_text}\n**Type:** {settings['stats_type'].title()}\n**Enabled:** {settings['enabled']}",
                    color=discord.Color.blue(),
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
