"""TennoGen notification - notify about TennoGen releases."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import get_guild_setting, set_guild_setting


def setup(bot, group=None):
    cmd = group.command(name="tennogen", description="Configure TennoGen release notifications (mods only).") if group else bot.tree.command(name="tennogen", description="Configure TennoGen notifications.")

    @cmd
    @app_commands.describe(
        action="Enable, disable, or status",
        channel="Channel for TennoGen notifications"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Status", value="status"),
    ])
    async def tennogen(interaction: discord.Interaction, action: app_commands.Choice[str], channel: discord.TextChannel = None):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        act = action.value
        if act == "status":
            ch_id = await get_guild_setting(interaction.guild.id, "tennogen_notify_channel_id")
            if not ch_id:
                return await interaction.response.send_message(
                    embed=obsidian_embed("TennoGen Notify", "TennoGen notifications **disabled**. Use **Enable** and pick a channel.", color=discord.Color.blue(), client=interaction.client),
                    ephemeral=True,
                )
            ch = interaction.guild.get_channel(int(ch_id))
            return await interaction.response.send_message(
                embed=obsidian_embed("TennoGen Notify", f"**Enabled** • TennoGen updates → {ch.mention if ch else ch_id}", color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )
        if act == "disable":
            await set_guild_setting(interaction.guild.id, "tennogen_notify_channel_id", "")
            return await interaction.response.send_message(
                embed=obsidian_embed("TennoGen Notify", "TennoGen notifications **disabled**.", color=discord.Color.orange(), client=interaction.client),
                ephemeral=True,
            )
        if act == "enable":
            if not channel:
                return await interaction.response.send_message("Pick a channel when enabling.", ephemeral=True)
            await set_guild_setting(interaction.guild.id, "tennogen_notify_channel_id", str(channel.id))
            return await interaction.response.send_message(
                embed=obsidian_embed("TennoGen Notify", f"TennoGen updates will be sent to {channel.mention}.", color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )
