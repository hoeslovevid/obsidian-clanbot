"""Weekly clan recap — optional channel post with goals, events, activity, Baro, LFG."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord.ext import tasks

from api.warframe_api import get_baro_status
from core.embed_templates import embed_template
from core.embed_footers import footer_for
from database import DB_PATH, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def _build_weekly_recap_embed(guild: discord.Guild, client) -> discord.Embed | None:
    """Compose recap body or None when there is nothing worth posting."""
    week_ago = (now_utc() - timedelta(days=7)).isoformat()
    week_start_ts = int((now_utc() - timedelta(days=7)).timestamp())
    fields: list[tuple[str, str, bool]] = []

    async with aiosqlite.connect(DB_PATH) as db:
        # Server goal progress
        cur = await db.execute(
            """
            SELECT metric, target, completed, week_end
            FROM server_goals
            WHERE guild_id=? AND completed=0
            ORDER BY week_end DESC LIMIT 1
            """,
            (guild.id,),
        )
        goal = await cur.fetchone()
        if goal:
            metric, target, _completed, week_end = goal
            col_map = {
                "messages": "messages_sent",
                "voice_minutes": "voice_minutes",
                "commands_used": "commands_used",
                "events_attended": "events_attended",
            }
            col = col_map.get(metric, "messages_sent")
            cur = await db.execute(
                f"SELECT COALESCE(SUM({col}), 0) FROM activity_stats "
                f"WHERE guild_id=? AND last_activity_date >= date('now', '-7 days')",
                (guild.id,),
            )
            current = int((await cur.fetchone())[0] or 0)
            pct = min(100, int(100 * current / target)) if target else 0
            fields.append((
                "🎯 Server Goal",
                f"**{metric.replace('_', ' ').title()}** — {current:,}/{target:,} ({pct}%) · ends {week_end}",
                False,
            ))

        # Events this week
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE guild_id=? AND start_ts >= ? AND COALESCE(ended, 0) = 0
            """,
            (guild.id, week_start_ts),
        )
        events_count = int((await cur.fetchone())[0] or 0)
        if events_count:
            fields.append(("📅 Events", f"**{events_count}** scheduled this week", True))

        # Top activity snippet
        cur = await db.execute(
            """
            SELECT user_id, COALESCE(SUM(messages_sent), 0) + COALESCE(SUM(voice_minutes), 0) AS score
            FROM activity_stats
            WHERE guild_id=? AND last_activity_date >= date('now', '-7 days')
            GROUP BY user_id
            ORDER BY score DESC LIMIT 3
            """,
            (guild.id,),
        )
        top = await cur.fetchall()
        if top:
            lines = []
            for uid, score in top:
                m = guild.get_member(int(uid))
                lines.append(f"• {m.display_name if m else uid} — {int(score):,} pts")
            fields.append(("⭐ Top Activity", "\n".join(lines), False))

        # Open LFG
        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild.id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)
        if open_lfg:
            fields.append(("🤝 LFG", f"**{open_lfg}** open post{'s' if open_lfg != 1 else ''}", True))

    # Baro summary
    try:
        is_active, baro = await get_baro_status()
        if baro:
            if is_active:
                fields.append(("🛸 Baro", "Baro Ki'Teer is **here** now!", True))
            else:
                act = baro.get("activation") or baro.get("Activation")
                if act:
                    fields.append(("🛸 Baro", f"Next visit: {act[:16]}", True))
    except Exception:
        pass

    if not fields:
        return None

    return embed_template(
        "showcase",
        "📰 Weekly Clan Recap",
        f"Your week in **{guild.name}** — <t:{int(now_utc().timestamp())}:D>",
        category="community",
        fields=fields,
        footer=footer_for("warframe_hub"),
        client=client,
        thumbnail=guild.icon.url if guild.icon else None,
    )


def create_weekly_recap_loop(bot):
    """Return the weekly recap task loop."""

    @tasks.loop(hours=6)
    async def weekly_recap_loop():
        try:
            for guild in bot.guilds:
                try:
                    ch_raw = await get_guild_setting(guild.id, "recap_channel_id")
                    if not ch_raw or not str(ch_raw).strip().isdigit():
                        continue
                    ch_id = int(ch_raw)
                    channel = guild.get_channel(ch_id)
                    if not isinstance(channel, discord.TextChannel):
                        continue

                    # Post once per ISO week
                    iso_week = now_utc().isocalendar()[:2]
                    week_key = f"{iso_week[0]}-W{iso_week[1]:02d}"
                    last = await get_guild_setting(guild.id, "weekly_recap_last_week")
                    if last == week_key:
                        continue
                    # Only post on Sunday (UTC) between 16:00–22:00
                    if now_utc().weekday() != 6:
                        continue
                    if not (16 <= now_utc().hour < 22):
                        continue

                    embed = await _build_weekly_recap_embed(guild, bot)
                    if not embed:
                        continue
                    await channel.send(embed=embed)
                    await set_guild_setting(guild.id, "weekly_recap_last_week", week_key)
                    logger.info("[weekly_recap] Posted for guild %s", guild.id)
                except Exception as e:
                    logger.error("[weekly_recap] guild %s: %s", guild.id, e, exc_info=True)
        except Exception as e:
            logger.error("[weekly_recap] loop error: %s", e, exc_info=True)

    @weekly_recap_loop.before_loop
    async def before_weekly_recap():
        await bot.wait_until_ready()

    return weekly_recap_loop
