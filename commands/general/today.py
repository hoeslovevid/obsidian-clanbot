"""Top-level /today — unified daily priorities panel."""
from __future__ import annotations

import discord

from core.embed_prefs import embed_kwargs
from core.progress_nudge import append_progress_nudge
from core.reply_helpers import reply_server_only
from core.today_panel import build_today_fields, gather_today_data, today_footer
from core.utils import ECONOMY_ENABLED, EMBED_COLORS, feature_off_embed, obsidian_embed


async def _run_today(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        return await reply_server_only(interaction)
    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=feature_off_embed("Economy", client=interaction.client),
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)
    data = await gather_today_data(
        interaction.guild.id,
        interaction.user.id,
        bot=interaction.client,
    )
    fields = build_today_fields(data)
    footer = today_footer(data)
    body = f"Here's what matters today in **{interaction.guild.name}**."
    body = await append_progress_nudge(
        body, interaction.guild.id, interaction.user.id, context="general",
    )

    embed = obsidian_embed(
        f"📅 Today · {interaction.user.display_name}",
        body,
        color=EMBED_COLORS["general"],
        template="profile",
        category="general",
        fields=fields,
        footer=footer,
        client=interaction.client,
        **(await embed_kwargs(interaction.guild.id, interaction.user.id)),
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot, group=None):
    """Register /today top-level shortcut."""

    @bot.tree.command(
        name="today",
        description="Your day at a glance — daily, bounties, Baro, LFG, events, and more.",
    )
    async def today_cmd(interaction: discord.Interaction):
        await _run_today(interaction)
