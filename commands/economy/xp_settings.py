"""XP settings command - configure level-up announcements (moderators only)."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod, XP_LEVELUP_CHANNEL_KEY
from database import get_guild_setting, set_guild_setting


def setup(bot, group=None):
    """Register the xp_settings command."""
    command_decorator = (
        group.command(name="settings", description="Configure XP level-up announcements (moderators only).")
        if group
        else bot.tree.command(name="settings", description="Configure XP level-up announcements (moderators only).")
    )

    @command_decorator
    @app_commands.describe(
        channel="Channel to send level-up announcements to (leave empty to view current setting)",
        disable="Set to True to disable level-up announcements"
    )
    async def xp_settings_cmd(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        disable: Optional[bool] = None,
    ):
        """Configure where level-up announcements are sent."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure XP settings.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        current = await get_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY)
        current_channel_id = int(current) if current and current.isdigit() else None

        if disable:
            await set_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY, "")
            msg = "Level-up announcements have been disabled."
        elif channel:
            await set_guild_setting(interaction.guild.id, XP_LEVELUP_CHANNEL_KEY, str(channel.id))
            msg = f"Level-up announcements will be sent to {channel.mention}."
        elif current_channel_id:
            ch = interaction.guild.get_channel(current_channel_id)
            msg = f"**Current:** Level-up announcements are sent to {ch.mention if ch else f'<#{current_channel_id}>'}.\n\nUse `channel` to change, or `disable` to turn off."
        else:
            msg = "Level-up announcements are not configured. Provide a `channel` to enable them."

        await interaction.response.send_message(
            embed=obsidian_embed(
                "⚙️ XP Settings",
                msg,
                color=discord.Color.blue(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
