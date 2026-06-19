"""Configure weekly mod KPI digest channel."""
from __future__ import annotations

import discord
from discord import app_commands

from core.utils import success_embed, is_mod
from database import set_guild_setting


def setup(bot, group=None):
    command_decorator = (
        group.command(
            name="mod_kpi_setup",
            description="Post weekly mod KPI digest to a staff channel (Mondays UTC).",
        )
        if group
        else bot.tree.command(
            name="mod_kpi_setup",
            description="Post weekly mod KPI digest to a staff channel.",
        )
    )

    @command_decorator
    @app_commands.describe(channel="Staff channel for the weekly KPI snapshot")
    async def mod_kpi_setup(interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await set_guild_setting(interaction.guild.id, "mod_kpi_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=success_embed(
                "Mod KPI digest configured",
                f"Weekly ticket snapshot will post in {channel.mention} "
                "(Mondays ~9–11 UTC). Use `/admin kpis` anytime for the full dashboard.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
