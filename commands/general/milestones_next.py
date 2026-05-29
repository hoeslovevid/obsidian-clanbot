"""Preview the next server member-count milestone."""
from __future__ import annotations

import discord
from discord import app_commands

from core.utils import obsidian_embed, render_bar, format_number, EMBED_COLORS


MILESTONE_TARGETS = (
    50, 100, 250, 500, 1000, 2500, 5000, 10000, 15000, 20000, 25000, 50000,
)


def _next_member_milestone(current: int) -> int | None:
    for target in MILESTONE_TARGETS:
        if current < target:
            return target
    if current <= 0:
        return MILESTONE_TARGETS[0]
    # Beyond listed targets — next round hundred
    remainder = current % 100
    if remainder == 0:
        return current + 100
    return current + (100 - remainder)


def setup(bot, group=None):
    """Top-level ``/milestones_next`` only — ``/tools`` is at the 25-subcommand cap."""
    group = None
    cmd = bot.tree.command(
        name="milestones_next",
        description="Next member milestone — how close the server is to the next count.",
    )

    @cmd
    async def milestones_next(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Server only", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=False)
        current = interaction.guild.member_count or 0
        nxt = _next_member_milestone(current)
        if nxt is None:
            return await interaction.followup.send(
                embed=obsidian_embed("🎯 Milestones", "No upcoming milestone target configured.", client=interaction.client),
            )
        remaining = max(0, nxt - current)
        pct = min(100.0, (100.0 * current / nxt) if nxt else 100.0)
        bar = render_bar(pct, length=12)
        desc = (
            f"**{interaction.guild.name}** has **{format_number(current)}** members.\n\n"
            f"**Next milestone:** {format_number(nxt)} members\n"
            f"**Remaining:** {format_number(remaining)} to go\n\n"
            f"{bar} · **{pct:.0f}%** there"
        )
        if remaining <= 10:
            desc += f"\n\n_Only **{remaining}** more {'member' if remaining == 1 else 'members'} — almost there!_"
        embed = obsidian_embed(
            "🎯 Next Member Milestone",
            desc,
            color=EMBED_COLORS["community"],
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer="Milestones auto-celebrate when member count is hit",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
