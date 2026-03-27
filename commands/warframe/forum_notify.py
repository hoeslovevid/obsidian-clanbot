"""Forum/news notification - notify when new Warframe forum posts."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting


def setup(bot, group=None):
    cmd = group.command(name="forum", description="Configure Warframe forum post notifications (mods only).") if group else bot.tree.command(name="forum", description="Configure forum notifications.")

    @cmd
    @app_commands.describe(action="Enable, disable, or status", channel="Channel for notifications")
    @app_commands.choices(action=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Status", value="status"),
    ])
    async def forum(interaction: discord.Interaction, action: app_commands.Choice[str], channel: discord.TextChannel = None):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        act = action.value
        if act == "status":
            ch_id = await get_guild_setting(interaction.guild.id, "forum_notify_channel_id")
            if not ch_id:
                return await interaction.response.send_message(
                    embed=obsidian_embed("Forum Notify", "Forum notifications disabled. Use Enable and pick a channel.", color=discord.Color.blue(), client=interaction.client),
                    ephemeral=True,
                )
            ch = interaction.guild.get_channel(int(ch_id))
            return await interaction.response.send_message(
                embed=obsidian_embed("Forum Notify", "Enabled. Posts go to " + (ch.mention if ch else str(ch_id)), color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )
        if act == "disable":
            await set_guild_setting(interaction.guild.id, "forum_notify_channel_id", "")
            return await interaction.response.send_message(
                embed=obsidian_embed("Forum Notify", "Disabled.", color=discord.Color.orange(), client=interaction.client),
                ephemeral=True,
            )
        if act == "enable" and channel:
            await set_guild_setting(interaction.guild.id, "forum_notify_channel_id", str(channel.id))
            return await interaction.response.send_message(
                embed=obsidian_embed("Forum Notify", "New forum posts will go to " + channel.mention, color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )
        return await interaction.response.send_message("Pick a channel when enabling.", ephemeral=True)
