"""Top-level /notifications — unified alert and DM status."""
from __future__ import annotations

import discord
from discord import app_commands

from core.action_panel_views import notifications_panel_view
from core.notifications_hub import build_notifications_status_embed
from core.refresh_panels import register_refresh_panel
from core.utils import error_embed


def setup(bot, group=None):
    async def notifications_status(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        embed = await build_notifications_status_embed(
            interaction.guild, interaction.user, client=interaction.client,
        )
        payload = {"guild_id": interaction.guild.id, "user_id": interaction.user.id}
        view = notifications_panel_view(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
        )
        msg = await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await register_refresh_panel(msg, "notifications", payload)

    if group is not None:
        group.command(name="notifications", description="Your watches, DMs, and guild alert feeds.")(
            notifications_status
        )
    else:
        bot.tree.add_command(
            app_commands.Command(
                name="notifications",
                description="Your watches, DMs, and guild alert feeds.",
                callback=notifications_status,
            )
        )
