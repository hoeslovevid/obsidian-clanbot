"""Daily DM digest for users who opt in via /preferences digest_dm."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite
import dateparser
import discord
from discord.ext import tasks

from api.warframe_api import get_baro_status
from core.embed_templates import embed_template
from core.utils import obsidian_embed
from database import (
    DB_PATH,
    get_digest_dm,
    get_guild_setting,
    get_quieter_mode,
    get_user_timezone,
    now_utc,
    set_guild_setting,
)

logger = logging.getLogger(__name__)

_DIGEST_HOUR_START = 8
_DIGEST_HOUR_END = 9


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


async def _streak_at_risk_line(guild_id: int, user_id: int, today_str: str) -> str | None:
    """Remind when daily is unclaimed and the user has a streak to lose."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT last_claim_date, streak_days FROM daily_claims WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        if not row:
            return None
        last_claim, streak = row[0], int(row[1] or 0)
        if last_claim == today_str or streak < 1:
            return None
        return f"🔥 **Streak at risk** — {streak} day{'s' if streak != 1 else ''} · claim `/economy daily` before reset"
    except Exception:
        return None


async def _mature_investments_line(guild_id: int, user_id: int) -> str | None:
    """List investments ready to collect, if the investments table exists."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='investments'"
            )
            if not await cur.fetchone():
                return None
            now_iso = now_utc().isoformat()
            cur = await db.execute(
                """
                SELECT COUNT(*) FROM investments
                WHERE guild_id=? AND user_id=? AND collected=0
                  AND mature_at IS NOT NULL AND mature_at <= ?
                """,
                (guild_id, user_id, now_iso),
            )
            count = int((await cur.fetchone())[0] or 0)
        if count <= 0:
            return None
        return f"📈 **{count}** investment{'s' if count != 1 else ''} ready — `/economy invest_collect`"
    except Exception as e:
        logger.debug("[digest] investments check skipped: %s", e)
        return None


def _in_digest_send_window(guild_id: int, user_id: int, tz_name: str | None) -> bool:
    """True when local time is in the digest hour window (default 08:00–09:00)."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = now_utc().astimezone(tz)
    return _DIGEST_HOUR_START <= local.hour < _DIGEST_HOUR_END


async def _section_on(guild_id: int, user_id: int, section: str) -> bool:
    """Per-feature digest opt-out: section is ON unless explicitly set to '0'."""
    val = await get_guild_setting(guild_id, f"user_digest_feat:{user_id}:{section}")
    return val != "0"


async def _build_user_digest(guild_id: int, user_id: int, *, quieter: bool) -> str | None:
    """Compose digest body or None when there is nothing worth sending."""
    today = now_utc().date()
    today_str = today.isoformat()
    lines: list[str] = []

    economy_on = await _section_on(guild_id, user_id, "economy")
    events_on = await _section_on(guild_id, user_id, "events")
    baro_on = await _section_on(guild_id, user_id, "baro")
    invest_on = await _section_on(guild_id, user_id, "investments")
    pets_on = await _section_on(guild_id, user_id, "pets")
    market_on = await _section_on(guild_id, user_id, "market")

    if economy_on:
        streak_line = await _streak_at_risk_line(guild_id, user_id, today_str)
        if streak_line:
            lines.append(streak_line)

    async with aiosqlite.connect(DB_PATH) as db:
        if economy_on:
            cur = await db.execute(
                "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            last_claim = row[0] if row else None
            if last_claim != today_str:
                lines.append("💰 **Daily reward** is unclaimed — use `/economy daily` before reset.")

        if not quieter and events_on:
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
                lines.append(
                    f"📅 **{events_today}** clan event{'s' if events_today != 1 else ''} scheduled today."
                )

    if not quieter and baro_on:
        baro_line = await _baro_soon_line()
        if baro_line:
            lines.append(baro_line)

    if invest_on:
        inv_line = await _mature_investments_line(guild_id, user_id)
        if inv_line:
            lines.append(inv_line)

    if pets_on:
        try:
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT hunger, happiness, last_fed, last_played, created_at, name "
                    "FROM pets WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                pet = await cur.fetchone()
            if pet:
                h = _apply_decay(pet[0] or 100, pet[2], pet[4], HUNGER_DECAY_PER_HOUR)
                hp = _apply_decay(pet[1] or 100, pet[3], pet[4], HAPPINESS_DECAY_PER_HOUR)
                if h < 50 or hp < 50:
                    lines.append(
                        f"🐾 **{pet[5] or 'Pet'}** needs care — `/economy pets`"
                    )
        except Exception:
            pass

    if market_on:
        try:
            from core.price_watchlist import digest_market_line

            mline = await digest_market_line(guild_id, user_id)
            if mline:
                lines.append(mline)
        except Exception:
            pass

    if not lines:
        return None
    return "\n".join(lines)


def create_digest_loop(bot: discord.Client):
    """Return a started tasks.loop for the daily digest."""

    @tasks.loop(hours=1)
    async def digest_dm_loop():
        if not bot.is_ready():
            return

        today_str = now_utc().date().isoformat()

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

            tz = await get_user_timezone(guild_id, user_id)
            if not _in_digest_send_window(guild_id, user_id, tz):
                continue

            sent_key = f"digest_dm_sent:{user_id}"
            if await get_guild_setting(guild_id, sent_key) == today_str:
                continue

            from core.quiet_hours import in_quiet_hours
            if await in_quiet_hours(guild_id, user_id):
                continue

            quieter = await get_quieter_mode(guild_id)
            body = await _build_user_digest(guild_id, user_id, quieter=quieter)
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
            embed = embed_template(
                "showcase",
                "☀️ Daily Digest",
                f"Quick snapshot for **{guild_name}**:\n\n{body}",
                category="general",
                client=bot,
                footer="Manage with /general preferences · digest_dm",
                brand=True,
            )
            try:
                from core.safe_send import safe_dm
                await safe_dm(user, embed=embed)
                await set_guild_setting(guild_id, sent_key, today_str)
            except Exception as e:
                logger.debug("[digest] DM failed for %s in %s: %s", user_id, guild_id, e)

    @digest_dm_loop.before_loop
    async def before_digest_dm_loop():
        await bot.wait_until_ready()
        await asyncio.sleep(45)

    return digest_dm_loop
