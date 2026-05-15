"""/tools my_stats — personal command-usage stats (#15).

Powered by the ``command_usage_stats`` table; the per-invocation counter is
incremented by the ``on_app_command_completion`` listener in ``bot.py``.
"""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, render_bar, EMBED_COLORS
from database import get_user_command_stats


_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _weekday_chart(counts: list[int]) -> str:
    """Render a small Mon-Sun bar chart using render_bar() per row."""
    peak = max(counts) if counts else 0
    if peak == 0:
        return "_No usage recorded yet — use a few slash commands and check back!_"
    rows = []
    for i, label in enumerate(_WEEKDAYS):
        bar = render_bar(counts[i] / peak, length=12, show_pct=False)
        rows.append(f"`{label}` {bar} `{counts[i]}`")
    return "\n".join(rows)


def setup(bot, group=None):
    cmd = (
        group.command(name="my_stats", description="See your personal slash command usage stats.")
        if group
        else bot.tree.command(name="my_stats", description="See your personal slash command usage stats.")
    )

    @cmd
    @app_commands.describe(user="Look at someone else's command stats (defaults to you).")
    async def my_stats(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Server only", "Use this command inside a server.", category="warning", client=interaction.client),
                ephemeral=True,
            )

        target = user or interaction.user
        await interaction.response.defer(ephemeral=user is None)

        stats = await get_user_command_stats(interaction.guild.id, target.id, top_n=10)
        total = stats["total"]

        if total == 0:
            embed = obsidian_embed(
                f"📊 Command stats — {target.display_name}",
                f"{target.mention} hasn't used any slash commands yet (or stats started recording recently).",
                category="general",
                client=interaction.client,
            )
            return await interaction.followup.send(embed=embed, ephemeral=user is None)

        top = stats["top"]
        max_top = top[0][1] if top else 1

        top_lines = []
        for i, (name, count) in enumerate(top, 1):
            bar = render_bar(count / max_top, length=10, show_pct=False)
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i:>2}`"
            top_lines.append(f"{medal} `/{name}` {bar} **{count:,}**")

        weekday_chart = _weekday_chart(stats["by_weekday"])
        peak_idx = stats["by_weekday"].index(max(stats["by_weekday"])) if any(stats["by_weekday"]) else 0
        peak_label = _WEEKDAYS[peak_idx]

        first_used = stats.get("first_used") or "—"
        first_used_short = first_used.split("T")[0] if first_used and "T" in first_used else first_used

        embed = obsidian_embed(
            f"📊 Command stats — {target.display_name}",
            f"> Total invocations: **{total:,}**\n"
            f"> Busiest day: **{peak_label}**\n"
            f"> Tracking since: `{first_used_short}`",
            category="general",
            client=interaction.client,
        )
        embed.add_field(
            name="🏆 Top commands",
            value="\n".join(top_lines),
            inline=False,
        )
        embed.add_field(
            name="📅 By day of week",
            value=weekday_chart,
            inline=False,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Stats are recorded per server. /general preferences to manage notifications.")

        await interaction.followup.send(embed=embed, ephemeral=user is None)
