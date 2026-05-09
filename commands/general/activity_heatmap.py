"""Server activity heatmap — message/coin-earn distribution by hour of day."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite

_BLOCKS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
_DAYS_CHOICES = [
    app_commands.Choice(name="Last 7 days", value=7),
    app_commands.Choice(name="Last 30 days", value=30),
    app_commands.Choice(name="Last 90 days", value=90),
]


def _bar(value: int, max_value: int) -> str:
    """Return a single block character scaled to the value."""
    if max_value == 0:
        return _BLOCKS[0]
    idx = int((value / max_value) * (len(_BLOCKS) - 1))
    return _BLOCKS[max(0, min(idx, len(_BLOCKS) - 1))]


def _build_chart(counts: list[int]) -> str:
    """Build a 24-column block-character bar chart from hourly counts."""
    peak = max(counts) if counts else 1
    bars = "".join(_bar(c, peak) for c in counts)
    # Hour labels every 6 hours below the bars
    labels = "0     6    12    18   23"
    return f"`{bars}`\n`{labels}`"


def setup(bot, group=None):
    cmd = (
        group.command(name="activity_heatmap", description="Show server activity by hour of day.")
        if group
        else bot.tree.command(name="activity_heatmap", description="Show server activity by hour of day.")
    )

    @cmd
    @app_commands.describe(
        days="Time window to analyse (default: 30 days)",
        user="Focus on a specific member instead of the whole server",
    )
    @app_commands.choices(days=_DAYS_CHOICES)
    async def activity_heatmap(
        interaction: discord.Interaction,
        days: Optional[app_commands.Choice[int]] = None,
        user: Optional[discord.Member] = None,
    ):
        """Display a 24-hour activity heatmap based on economy transaction timestamps."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Server only.", category="error", client=interaction.client),
                ephemeral=True,
            )

        window = days.value if days else 30
        is_self = user is not None and user.id == interaction.user.id
        is_public = user is None or not is_self
        await interaction.response.defer(ephemeral=not is_public)

        async with aiosqlite.connect(DB_PATH) as db:
            if user:
                cur = await db.execute("""
                    SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hr, COUNT(*) AS cnt
                    FROM economy_transactions
                    WHERE guild_id=? AND user_id=?
                      AND created_at >= datetime('now', ? || ' days')
                    GROUP BY hr
                    ORDER BY hr
                """, (interaction.guild.id, user.id, f"-{window}"))
            else:
                cur = await db.execute("""
                    SELECT CAST(strftime('%H', created_at) AS INTEGER) AS hr, COUNT(*) AS cnt
                    FROM economy_transactions
                    WHERE guild_id=?
                      AND created_at >= datetime('now', ? || ' days')
                    GROUP BY hr
                    ORDER BY hr
                """, (interaction.guild.id, f"-{window}"))
            rows = await cur.fetchall()

        counts = [0] * 24
        for hr, cnt in rows:
            if 0 <= hr <= 23:
                counts[hr] = cnt

        total_events = sum(counts)
        if total_events == 0:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📊 No Data",
                    f"No activity recorded in the last {window} days.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        peak_hour = counts.index(max(counts))
        quiet_hour = counts.index(min(counts))
        chart = _build_chart(counts)

        scope = user.display_name if user else interaction.guild.name
        fields = [
            ("🕐 Peak Hour", f"**{peak_hour:02d}:00 UTC** ({counts[peak_hour]:,} events)", True),
            ("🌙 Quietest", f"**{quiet_hour:02d}:00 UTC** ({counts[quiet_hour]:,} events)", True),
            ("📅 Window", f"Last **{window}** days", True),
        ]

        embed = obsidian_embed(
            f"📊 Activity Heatmap — {scope}",
            f"Economy events by UTC hour of day:\n\n{chart}\n\n"
            f"-# Each bar = relative activity volume. Times are UTC.",
            category="general",
            thumbnail=interaction.guild.icon.url if interaction.guild.icon and not user else None,
            fields=fields,
            footer=f"{total_events:,} total events  ·  Last {window} days",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=not is_public)
