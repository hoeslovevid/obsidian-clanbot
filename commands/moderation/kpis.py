"""Moderator KPI dashboard (moderators only)."""
import discord
from discord import app_commands
from typing import Optional
import aiosqlite

from core.utils import obsidian_embed, is_mod
from database import DB_PATH


def setup(bot, group=None):
    command_decorator = group.command(
        name="kpis",
        description="Moderator KPI dashboard (tickets, complaints, events).",
    ) if group else bot.tree.command(
        name="kpis",
        description="Moderator KPI dashboard (tickets, complaints, events).",
    )

    @command_decorator
    @app_commands.describe(days="Lookback window in days (default 30)")
    async def kpis(interaction: discord.Interaction, days: Optional[int] = 30):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can view KPIs.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        d = days or 30
        if d < 1:
            d = 1
        if d > 365:
            d = 365

        async with aiosqlite.connect(DB_PATH) as db:
            # Tickets created/closed
            cur = await db.execute(
                """
                SELECT
                    COUNT(*) AS created,
                    SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) AS closed
                FROM tickets
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', ?)
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            t_created, t_closed = await cur.fetchone()

            # Avg first response minutes
            cur = await db.execute(
                """
                SELECT AVG((julianday(first_response_at) - julianday(created_at)) * 1440.0)
                FROM tickets
                WHERE guild_id=? AND first_response_at IS NOT NULL AND first_response_at!=''
                  AND datetime(created_at) >= datetime('now', ?)
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            avg_first = (await cur.fetchone())[0]

            # Avg close minutes
            cur = await db.execute(
                """
                SELECT AVG((julianday(closed_at) - julianday(created_at)) * 1440.0)
                FROM tickets
                WHERE guild_id=? AND status='closed' AND closed_at IS NOT NULL AND closed_at!=''
                  AND datetime(created_at) >= datetime('now', ?)
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            avg_close = (await cur.fetchone())[0]

            # Top closers
            cur = await db.execute(
                """
                SELECT closed_by, COUNT(*)
                FROM tickets
                WHERE guild_id=? AND status='closed' AND closed_by IS NOT NULL
                  AND datetime(closed_at) >= datetime('now', ?)
                GROUP BY closed_by
                ORDER BY COUNT(*) DESC
                LIMIT 5
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            top_closers = await cur.fetchall()

            # Top claimers
            cur = await db.execute(
                """
                SELECT assigned_to, COUNT(*)
                FROM tickets
                WHERE guild_id=? AND assigned_to IS NOT NULL
                  AND datetime(created_at) >= datetime('now', ?)
                GROUP BY assigned_to
                ORDER BY COUNT(*) DESC
                LIMIT 5
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            top_claimers = await cur.fetchall()

            # Complaint actions
            cur = await db.execute(
                """
                SELECT actor_id, COUNT(*)
                FROM complaint_actions
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', ?)
                GROUP BY actor_id
                ORDER BY COUNT(*) DESC
                LIMIT 5
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            top_complaints = await cur.fetchall()

            cur = await db.execute(
                """
                SELECT AVG(satisfaction_rating), COUNT(satisfaction_rating)
                FROM tickets
                WHERE guild_id=? AND satisfaction_rating IS NOT NULL
                  AND datetime(closed_at) >= datetime('now', ?)
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            sat_row = await cur.fetchone()
            avg_sat, sat_count = (sat_row[0], sat_row[1]) if sat_row else (None, 0)

            # Events created
            cur = await db.execute(
                """
                SELECT COUNT(*)
                FROM events
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', ?)
                """,
                (interaction.guild.id, f"-{d} days"),
            )
            events_created = (await cur.fetchone())[0]

            # Week-over-week ticket volume
            cur = await db.execute(
                """
                SELECT COUNT(*) FROM tickets
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-7 days')
                """,
                (interaction.guild.id,),
            )
            tickets_week = int((await cur.fetchone())[0] or 0)
            cur = await db.execute(
                """
                SELECT COUNT(*) FROM tickets
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-14 days')
                  AND datetime(created_at) < datetime('now', '-7 days')
                """,
                (interaction.guild.id,),
            )
            tickets_prev_week = int((await cur.fetchone())[0] or 0)

        def trend_arrow(current: int, previous: int) -> str:
            if previous == 0:
                return "→" if current == 0 else "↑"
            if current > previous:
                return "↑"
            if current < previous:
                return "↓"
            return "→"

        def fmt_minutes(val) -> str:
            if val is None:
                return "—"
            try:
                m = float(val)
                if m < 1:
                    return "<1m"
                if m < 60:
                    return f"{m:.0f}m"
                h = m / 60.0
                return f"{h:.1f}h"
            except Exception:
                return "—"

        def fmt_top(rows) -> str:
            if not rows:
                return "—"
            out = []
            for uid, cnt in rows:
                if not uid:
                    continue
                out.append(f"<@{int(uid)}> — **{int(cnt)}**")
            return "\n".join(out) if out else "—"

        sat_text = "—"
        if sat_count and avg_sat is not None:
            sat_text = f"**{float(avg_sat):.1f}/5** ({int(sat_count)} ratings)"

        fields = [
            ("🎫 Tickets", f"**Created:** {int(t_created or 0)}\n**Closed:** {int(t_closed or 0)}\n**7d trend:** {trend_arrow(tickets_week, tickets_prev_week)} ({tickets_week} vs {tickets_prev_week} prior wk)", True),
            ("⏱️ SLA", f"**Avg first response:** {fmt_minutes(avg_first)}\n**Avg close:** {fmt_minutes(avg_close)}", True),
            ("⭐ Satisfaction", sat_text, True),
            ("🧑‍⚖️ Top closers", fmt_top(top_closers), True),
            ("🫡 Top claimers", fmt_top(top_claimers), True),
            ("🧾 Complaint actions", fmt_top(top_complaints), True),
            ("🗓️ Events", f"**Created:** {int(events_created or 0)}", True),
        ]

        embed = obsidian_embed(
            f"📊 Moderator KPIs (last {d} days)",
            "High-level workload + responsiveness metrics.",
            color=discord.Color.blurple(),
            fields=fields,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

