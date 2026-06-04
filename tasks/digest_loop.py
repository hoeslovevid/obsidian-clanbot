"""Daily DM digest for users who opt in via /preferences digest_dm."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite
import dateparser
import discord
from discord.ext import tasks

from api.warframe_api import get_baro_status
from core.utils import obsidian_embed
from database import DB_PATH, get_digest_dm, get_guild_setting, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def _baro_soon_line() -> str | None:
    """Return a short Baro line when arrival is within ~24 hours and he is not active yet."""
    try:
        is_active, data = await get_baro_status()
        if is_active or not data:
            return None
        activation = data.get("activation") or data.get("Activation")
        if not activation:
            return None
        act_dt = dateparser.parse(activation, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True})
        if not act_dt:
            return None
        if act_dt.tzinfo is None:
            act_dt = act_dt.replace(tzinfo=timezone.utc)
        delta = act_dt - now_utc()
        if timedelta(0) <= delta <= timedelta(hours=24):
            return f"🛸 **Baro** arrives <t:{int(act_dt.timestamp())}:R> (<t:{int(act_dt.timestamp())}:F>)"
    except Exception as e:
        logger.debug("[digest] baro check failed: %s", e)
    return None


async def _build_user_digest(guild_id: int, user_id: int) -> str | None:
    """Compose digest body or None when there is nothing worth sending."""
    today = now_utc().date()
    today_str = today.isoformat()
    lines: list[str] = []

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        last_claim = row[0] if row else None
        if last_claim != today_str:
            lines.append("💰 **Daily reward** is unclaimed — use `/economy daily` before reset.")

        day_start = int(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        day_end = day_start + 86400
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE guild_id=? AND start_ts >= ? AND start_ts < ? AND COALESCE(ended, 0) = 0
            """,
            (guild_id, day_start, day_end),
        )
        events_today = int((await cur.fetchone())[0] or 0)
        if events_today:
            lines.append(f"📅 **{events_today}** clan event{'s' if events_today != 1 else ''} scheduled today.")

    baro_line = await _baro_soon_line()
    if baro_line:
        lines.append(baro_line)

    if not lines:
        return None
    return "\n".join(lines)


def create_digest_loop(bot: discord.Client):
    """Return a started tasks.loop for the daily digest."""

    @tasks.loop(hours=1)
    async def digest_dm_loop():
        if not bot.is_ready():
            return

        now = now_utc()
        # Send once per user per UTC day, between 12:00–13:00 UTC
        if not (12 <= now.hour < 13):
            return

        today_str = now.date().isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT guild_id, key
                FROM guild_settings
                WHERE key LIKE 'user_digest_dm:%' AND value = '1'
                """
            )
            rows = await cur.fetchall()

        for guild_id, pref_key in rows:
            try:
                user_id = int(str(pref_key).rsplit(":", 1)[-1])
            except (ValueError, IndexError):
                continue

            if not await get_digest_dm(guild_id, user_id):
                continue

            sent_key = f"digest_dm_sent:{user_id}"
            if await get_guild_setting(guild_id, sent_key) == today_str:
                continue

            body = await _build_user_digest(guild_id, user_id)
            if not body:
                continue

            user = bot.get_user(user_id)
            if user is None:
                try:
                    user = await bot.fetch_user(user_id)
                except Exception:
                    continue

            guild = bot.get_guild(guild_id)
            guild_name = guild.name if guild else "your server"
            embed = obsidian_embed(
                "☀️ Daily Digest",
                f"Quick snapshot for **{guild_name}**:\n\n{body}",
                category="general",
                client=bot,
                footer="Manage with /general preferences · digest_dm",
            )
            try:
                await user.send(embed=embed)
                await set_guild_setting(guild_id, sent_key, today_str)
            except Exception as e:
                logger.debug("[digest] DM failed for %s in %s: %s", user_id, guild_id, e)

    @digest_dm_loop.before_loop
    async def before_digest_dm_loop():
        await bot.wait_until_ready()

    return digest_dm_loop
