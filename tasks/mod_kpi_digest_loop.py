"""Weekly moderator KPI digest — optional channel post for staff."""
from __future__ import annotations

import logging

import aiosqlite
import discord
from discord.ext import tasks

from core.embed_templates import embed_template
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def _build_mod_kpi_embed(guild: discord.Guild, client) -> discord.Embed | None:
    """7-day KPI snapshot for moderators."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END)
            FROM tickets
            WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        created, closed = await cur.fetchone()

        cur = await db.execute(
            """
            SELECT AVG((julianday(first_response_at) - julianday(created_at)) * 1440.0)
            FROM tickets
            WHERE guild_id=? AND first_response_at IS NOT NULL AND first_response_at!=''
              AND datetime(created_at) >= datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        avg_first = (await cur.fetchone())[0]

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND status='open'
              AND (first_response_at IS NULL OR first_response_at='')
            """,
            (guild.id,),
        )
        awaiting = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        tickets_week = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-14 days')
              AND datetime(created_at) < datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        tickets_prev = int((await cur.fetchone())[0] or 0)

        cur = await db.execute(
            """
            SELECT AVG(satisfaction_rating), COUNT(satisfaction_rating)
            FROM tickets
            WHERE guild_id=? AND satisfaction_rating IS NOT NULL
              AND datetime(closed_at) >= datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        sat_row = await cur.fetchone()

    if not any([created, closed, awaiting, tickets_week]):
        return None

    def fmt_minutes(val) -> str:
        if val is None:
            return "—"
        try:
            m = float(val)
            if m < 1:
                return "<1m"
            if m < 60:
                return f"{m:.0f}m"
            return f"{m / 60.0:.1f}h"
        except Exception:
            return "—"

    trend = "→"
    if tickets_week > tickets_prev:
        trend = "↑"
    elif tickets_week < tickets_prev:
        trend = "↓"

    sat_text = "—"
    if sat_row and sat_row[1]:
        sat_text = f"**{float(sat_row[0]):.1f}/5** ({int(sat_row[1])} ratings)"

    fields = [
        ("🎫 Tickets (7d)", f"**Opened:** {int(created or 0)}\n**Closed:** {int(closed or 0)}\n**Trend:** {trend} ({tickets_week} vs {tickets_prev} prior wk)", True),
        ("⏱️ Response", f"**Avg first reply:** {fmt_minutes(avg_first)}\n**Awaiting first reply:** {awaiting}", True),
        ("⭐ Satisfaction", sat_text, True),
    ]

    return embed_template(
        "showcase",
        "📊 Weekly Mod KPI Digest",
        f"Staff snapshot for **{guild.name}** — run `/admin kpis` for the full dashboard.",
        category="moderation",
        fields=fields,
        client=client,
    )


def create_mod_kpi_digest_loop(bot):
    """Return the weekly mod KPI digest task loop."""

    @tasks.loop(hours=6)
    async def mod_kpi_digest_loop():
        try:
            for guild in bot.guilds:
                try:
                    ch_raw = await get_guild_setting(guild.id, "mod_kpi_channel_id")
                    if not ch_raw or not str(ch_raw).strip().isdigit():
                        continue
                    channel = guild.get_channel(int(ch_raw))
                    if not isinstance(channel, discord.TextChannel):
                        continue

                    iso_week = now_utc().isocalendar()[:2]
                    week_key = f"{iso_week[0]}-W{iso_week[1]:02d}"
                    last = await get_guild_setting(guild.id, "mod_kpi_digest_last_week")
                    if last == week_key:
                        continue
                    if now_utc().weekday() != 0:
                        continue
                    if not (9 <= now_utc().hour < 11):
                        continue

                    embed = await _build_mod_kpi_embed(guild, bot)
                    if not embed:
                        continue
                    await channel.send(embed=embed)
                    await set_guild_setting(guild.id, "mod_kpi_digest_last_week", week_key)
                    logger.info("[mod_kpi_digest] Posted for guild %s", guild.id)
                except Exception as e:
                    logger.error("[mod_kpi_digest] guild %s: %s", guild.id, e, exc_info=True)
        except Exception as e:
            logger.error("[mod_kpi_digest] loop error: %s", e, exc_info=True)

    @mod_kpi_digest_loop.before_loop
    async def before_mod_kpi_digest():
        await bot.wait_until_ready()

    return mod_kpi_digest_loop
