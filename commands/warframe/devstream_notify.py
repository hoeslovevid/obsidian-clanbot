"""Devstream notification setup command."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import dateparser  # type: ignore

from utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting, DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the devstream_notify command."""
    
    @bot.tree.command(name="devstream_notify", description="Configure devstream notifications (moderators only).")
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to send devstream notifications to"
    )
    async def devstream_notify(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure devstream notifications."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure devstream notifications.",
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
                        "Please specify a channel for devstream notifications.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_guild_setting(interaction.guild.id, "devstream_channel_id", str(channel.id))
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Devstream Notifications Configured",
                    f"Devstream notifications will be sent to {channel.mention}.\n\n"
                    "Note: Devstream dates are manually tracked. Use `/devstream_set` to set the next devstream date.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            await set_guild_setting(interaction.guild.id, "devstream_channel_id", "")
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Devstream Notifications Disabled",
                    "Devstream notifications have been disabled.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "status":
            channel_id_str = await get_guild_setting(interaction.guild.id, "devstream_channel_id")
            next_devstream = await get_guild_setting(interaction.guild.id, "next_devstream_date")
            
            if not channel_id_str:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📺 Devstream Notifications Status",
                        "Devstream notifications are not configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            try:
                channel_id = int(channel_id_str)
                channel_obj = interaction.guild.get_channel(channel_id)
                status_text = f"**Channel:** {channel_obj.mention if channel_obj else f'Channel ID: {channel_id}'}\n**Status:** Enabled\n"
                
                if next_devstream:
                    try:
                        devstream_date = dateparser.parse(next_devstream, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                        if devstream_date:
                            now = datetime.now(timezone.utc)
                            if devstream_date > now:
                                status_text += f"**Next Devstream:** <t:{int(devstream_date.timestamp())}:F>"
                            else:
                                status_text += f"**Next Devstream:** Past (needs update)"
                    except Exception:
                        status_text += f"**Next Devstream:** {next_devstream}"
                else:
                    status_text += "**Next Devstream:** Not set (use `/devstream_set`)"
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📺 Devstream Notifications Status",
                        status_text,
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except ValueError:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "📺 Devstream Notifications Status",
                        "Devstream notifications are configured but channel ID is invalid.",
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
    
    @bot.tree.command(name="devstream_set", description="Set the next devstream date (moderators only).")
    @app_commands.describe(
        date="Date and time of the next devstream (e.g., 'Friday 2pm EST' or '2024-01-19 14:00')"
    )
    async def devstream_set(interaction: discord.Interaction, date: str):
        """Set the next devstream date."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can set devstream dates.",
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
        
        # Parse the date
        parsed_date = dateparser.parse(date, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not parsed_date:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Date",
                    f"Could not parse date: '{date}'\n\nTry formats like:\n• 'Friday 2pm EST'\n• '2024-01-19 14:00'\n• 'next Friday at 2pm'",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Store as ISO format
        await set_guild_setting(interaction.guild.id, "next_devstream_date", parsed_date.isoformat())
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Devstream Date Set",
                f"Next devstream scheduled for: <t:{int(parsed_date.timestamp())}:F>\n\n"
                "Notifications will be sent 24 hours and 1 hour before the devstream.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
