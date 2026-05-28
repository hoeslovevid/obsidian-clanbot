"""Near-miss achievement hints for /profile (QoL #18)."""
from __future__ import annotations

from typing import Any, Optional

import aiosqlite  # type: ignore

from database import DB_PATH


# (achievement_id, display_name, target) — current value resolved from profile_data
_TRACKED: list[tuple[str, str, str, int]] = [
    ("first_message", "First Message", "messages_sent", 1),
    ("hundred_messages", "Century", "messages_sent", 100),
    ("thousand_messages", "Millennium", "messages_sent", 1000),
    ("ten_thousand_messages", "Legend", "messages_sent", 10000),
    ("level_10", "Rising Star", "level", 10),
    ("level_25", "Veteran", "level", 25),
    ("level_50", "Master", "level", 50),
    ("level_100", "Grandmaster", "level", 100),
    ("voice_hour", "Voice Active", "voice_minutes", 60),
    ("voice_ten_hours", "Voice Veteran", "voice_minutes", 600),
    ("voice_100_hours", "Voice Centurion", "voice_minutes", 6000),
    ("daily_streak_10", "Dedicated", "daily_streak", 10),
    ("first_million", "Millionaire", "balance", 1_000_000),
    ("event_first", "First Ops", "events_attended", 1),
    ("event_10", "Regular", "events_attended", 10),
    ("event_50", "Veteran Attendee", "events_attended", 50),
]


def _current(profile_data: dict[str, Any], field: str) -> int:
    if field == "balance":
        return int(profile_data.get("balance") or 0)
    if field == "level":
        return int(profile_data.get("level") or 0)
    return int(profile_data.get(field) or 0)


async def get_achievement_nudges(
    guild_id: int,
    user_id: int,
    profile_data: dict[str, Any],
    *,
    unlocked_ids: Optional[set[str]] = None,
    max_n: int = 3,
) -> list[str]:
    """Return human-readable lines like ``2 more daily claims until **Dedicated**``."""
    if unlocked_ids is None:
        unlocked_ids = set()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT achievement_id FROM achievements WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            unlocked_ids = {str(r[0]) for r in await cur.fetchall()}

    candidates: list[tuple[int, str]] = []
    for ach_id, name, field, target in _TRACKED:
        if ach_id in unlocked_ids:
            continue
        if target <= 0:
            continue
        cur_val = _current(profile_data, field)
        if cur_val >= target:
            continue
        remaining = target - cur_val
        pct = cur_val / target
        if pct < 0.25 and remaining > max(target * 0.5, 5):
            continue  # too far away — skip noise
        if field == "voice_minutes":
            if remaining >= 60:
                rem_txt = f"{remaining // 60}h {remaining % 60}m more voice time"
            else:
                rem_txt = f"{remaining} more minute{'s' if remaining != 1 else ''} in voice"
        elif field == "daily_streak":
            rem_txt = f"{remaining} more daily claim{'s' if remaining != 1 else ''}"
        elif field == "balance":
            rem_txt = f"{remaining:,} more coins"
        elif field == "messages_sent":
            rem_txt = f"{remaining:,} more message{'s' if remaining != 1 else ''}"
        elif field == "events_attended":
            rem_txt = f"{remaining} more event RSVP{'s' if remaining != 1 else ''}"
        elif field == "level":
            rem_txt = f"{remaining} more level{'s' if remaining != 1 else ''}"
        else:
            rem_txt = f"{remaining} more"
        line = f"{rem_txt} until **{name}**"
        candidates.append((int(pct * 1000), line))

    candidates.sort(key=lambda x: -x[0])
    return [line for _, line in candidates[: max(0, int(max_n))]]
