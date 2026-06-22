"""Top-level /hq — member-facing clan dashboard."""
from __future__ import annotations

import discord
from discord import app_commands

from core.action_panel_views import clan_hq_panel_view
from core.clan_hq import build_clan_hq_embed
from core.refresh_panels import register_refresh_panel
from core.utils import error_embed


def setup(bot, group=None):
    async def clan_hq(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=False)
        embed = await build_clan_hq_embed(
            interaction.guild,
            client=interaction.client,
            user_id=interaction.user.id,
        )
        payload = {"guild_id": interaction.guild.id, "user_id": interaction.user.id}
        view = clan_hq_panel_view(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
        )
        msg = await interaction.followup.send(embed=embed, view=view)
        await register_refresh_panel(msg, "clan_hq", payload)

    if group is not None:
        group.command(name="hq", description="Clan HQ — LFG, events, Baro, and streamers at a glance.")(clan_hq)
    else:
        bot.tree.add_command(
            app_commands.Command(
                name="hq",
                description="Clan HQ — LFG, events, Baro, and streamers at a glance.",
                callback=clan_hq,
            )
        )
