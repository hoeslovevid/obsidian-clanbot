"""Per-user quiet hours for suppressing bot-initiated nudge DMs.

Stored per guild under ``user_quiet_hours:{user_id}`` as ``"START-END"`` (24h
local hours, e.g. ``"22-7"``). Applies to *bot-initiated* nudges (daily streak
reminder, daily digest) — never to user-requested notifications like reminders.
"""
from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

from database import get_guild_setting, get_user_timezone, now_utc


def parse_quiet_hours(value: Optional[str]) -> Optional[tuple[int, int]]:
    """Parse a ``"START-END"`` string into ``(start, end)`` 24h hours, or None."""
    if not value:
        return None
    try:
        start_s, end_s = value.split("-", 1)
        start, end = int(start_s), int(end_s)
    except (ValueError, AttributeError):
        return None
    if 0 <= start <= 23 and 0 <= end <= 23 and start != end:
        return (start, end)
    return None


async def get_quiet_hours(guild_id: int, user_id: int) -> Optional[tuple[int, int]]:
    return parse_quiet_hours(await get_guild_setting(guild_id, f"user_quiet_hours:{user_id}"))


async def in_quiet_hours(guild_id: int, user_id: int) -> bool:
    """True when the user's local time falls inside their configured quiet window."""
    window = await get_quiet_hours(guild_id, user_id)
    if not window:
        return False
    start, end = window
    try:
        tz = ZoneInfo(await get_user_timezone(guild_id, user_id) or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    hour = now_utc().astimezone(tz).hour
    if start < end:
        return start <= hour < end
    # Wraps past midnight (e.g. 22-7)
    return hour >= start or hour < end
