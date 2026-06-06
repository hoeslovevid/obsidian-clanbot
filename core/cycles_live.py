"""Shared open-world cycle embed builders and live-panel helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore

from core.embed_templates import embed_template
from core.utils import render_bar
from database import DB_PATH, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)

CETUS_CYCLE_SECONDS = 150 * 60
VALLIS_CYCLE_SECONDS = 40 * 60
CAMBION_CYCLE_SECONDS = 8 * 3600

# Last embed fingerprint per live panel message — skip redundant PATCH edits
_cycle_live_embed_cache: dict[tuple[int, int, int], str] = {}


def format_time_remaining(expiry_time: datetime) -> str:
    """Format time remaining until cycle change."""
    now = datetime.now(timezone.utc)
    time_remaining = expiry_time - now

    if time_remaining.total_seconds() <= 0:
        return "Just changed"

    total_seconds = int(time_remaining.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_cycle_progress(expiry_time: datetime, cycle_total_seconds: int) -> tuple[str, str]:
    """Return (countdown_str, progress_bar) for a cycle."""
    now = datetime.now(timezone.utc)
    elapsed = (expiry_time - now).total_seconds()
    if elapsed <= 0:
        return "Just changed", render_bar(100, length=10)
    if cycle_total_seconds <= 0:
        return format_time_remaining(expiry_time), ""
    time_elapsed = cycle_total_seconds - elapsed
    progress_pct = min(100, max(0, int(100 * time_elapsed / cycle_total_seconds)))
    return format_time_remaining(expiry_time), render_bar(progress_pct, length=10)


def build_cycle_fields(cycles_data: dict) -> list[tuple[str, str, bool]]:
    """Build embed fields from cycle data. Handles graceful degradation (partial data)."""
    fields: list[tuple[str, str, bool]] = []

    if cycles_data.get("cetus"):
        cetus = cycles_data["cetus"]
        is_day = cetus.get("isDay", False)
        state = "☀️ Day" if is_day else "🌙 Night"
        expiry = cetus.get("expiry", "")
        try:
            expiry_time = dateparser.parse(
                expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, CETUS_CYCLE_SECONDS)
                value = (
                    f"{state}\n⏱️ {time_str}\n{progress_bar}\n"
                    f"🕐 <t:{int(expiry_time.timestamp())}:F>\n"
                    f"<t:{int(expiry_time.timestamp())}:R>"
                )
            else:
                value = state
        except Exception:
            value = state
        fields.append(("🌅 Cetus", value, True))

    if cycles_data.get("vallis"):
        vallis = cycles_data["vallis"]
        is_warm = vallis.get("isWarm", False)
        state = "🔥 Warm" if is_warm else "❄️ Cold"
        expiry = vallis.get("expiry", "")
        try:
            expiry_time = dateparser.parse(
                expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, VALLIS_CYCLE_SECONDS)
                value = (
                    f"{state}\n⏱️ {time_str}\n{progress_bar}\n"
                    f"🕐 <t:{int(expiry_time.timestamp())}:F>\n"
                    f"<t:{int(expiry_time.timestamp())}:R>"
                )
            else:
                value = state
        except Exception:
            value = state
        fields.append(("❄️ Fortuna", value, True))

    if cycles_data.get("cambion"):
        cambion = cycles_data["cambion"]
        state = cambion.get("state", "Unknown")
        state_display = (
            "🔴 Fass"
            if state.lower() == "fass"
            else "🟢 Vome"
            if state.lower() == "vome"
            else state.title()
        )
        expiry = cambion.get("expiry", "")
        try:
            expiry_time = dateparser.parse(
                expiry, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
            )
            if expiry_time:
                time_str, progress_bar = format_cycle_progress(expiry_time, CAMBION_CYCLE_SECONDS)
                value = (
                    f"{state_display}\n⏱️ {time_str}\n{progress_bar}\n"
                    f"🕐 <t:{int(expiry_time.timestamp())}:F>\n"
                    f"<t:{int(expiry_time.timestamp())}:R>"
                )
            else:
                value = state_display
        except Exception:
            value = state_display
        fields.append(("🦠 Deimos", value, True))

    return fields


def build_cycles_live_embed(client, cycles_data: dict) -> discord.Embed:
    """Showcase warframe_status embed for the pinned live cycles panel."""
    success = {k: v for k, v in (cycles_data or {}).items() if v}
    fields = build_cycle_fields(success)
    failed = [k for k in ("cetus", "vallis", "cambion") if k not in success]
    now_ts = int(datetime.now(timezone.utc).timestamp())
    intro = f"> Live open-world cycles · updated <t:{now_ts}:R>"
    if failed:
        intro += f"\n> _Partial data: {', '.join(failed)} unavailable_"

    return embed_template(
        "warframe_status",
        "🌍 Open World Cycles",
        intro,
        variant="world_state",
        platform="pc",
        client=client,
        fields=fields,
        footer="Pinned live panel · **Update data** refreshes · /warframe cycles",
    )


def cycles_embed_fingerprint(embed: discord.Embed) -> str:
    """Stable string for skip-if-unchanged edit logic."""
    parts = [embed.title or "", embed.description or ""]
    for field in embed.fields:
        parts.extend([field.name, field.value])
    return "|".join(parts)


def get_cycle_live_embed_cache() -> dict[tuple[int, int, int], str]:
    return _cycle_live_embed_cache


async def guild_skips_cycle_pings(guild_id: int) -> bool:
    """True when flip pings should be suppressed (panel-only mode)."""
    mode = await get_guild_setting(guild_id, "cycle_notify_mode")
    if mode == "panel":
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM cycle_live_messages WHERE guild_id=? LIMIT 1",
            (guild_id,),
        )
        row = await cur.fetchone()
    return row is not None


async def get_cycle_live_message_id(guild_id: int, channel_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT message_id FROM cycle_live_messages
            WHERE guild_id=? AND channel_id=?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (guild_id, channel_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else None


async def register_cycle_live_message(
    guild_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    """Persist live panel row and enable panel-only notify mode for the guild."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM cycle_live_messages WHERE guild_id=?",
            (guild_id,),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO cycle_live_messages
            (guild_id, channel_id, message_id, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, channel_id, message_id, now),
        )
        await db.commit()
    await set_guild_setting(guild_id, "cycle_notify_mode", "panel")
    for key in list(_cycle_live_embed_cache):
        if key[0] == guild_id:
            del _cycle_live_embed_cache[key]


async def delete_cycle_live_message(
    guild_id: int,
    channel_id: int,
    message_id: int,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            DELETE FROM cycle_live_messages
            WHERE guild_id=? AND channel_id=? AND message_id=?
            """,
            (guild_id, channel_id, message_id),
        )
        await db.commit()
    _cycle_live_embed_cache.pop((guild_id, channel_id, message_id), None)


async def get_guild_cycle_panel_channel_id(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id FROM cycle_live_messages WHERE guild_id=? LIMIT 1",
            (guild_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else None
