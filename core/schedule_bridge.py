"""Personal upcoming events + LFG jump links for /today and /hq."""
from __future__ import annotations

import time
from typing import Any

import aiosqlite

from database import DB_PATH


def _lfg_jump(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


async def gather_personal_schedule(
    guild_id: int,
    user_id: int,
    *,
    hours_ahead: int = 24,
) -> dict[str, Any]:
    """RSVP'd events and open LFG posts for the next ``hours_ahead`` hours."""
    now_ts = int(time.time())
    cutoff_ts = now_ts + hours_ahead * 3600
    out: dict[str, Any] = {
        "events": [],
        "lfg_hosting": [],
        "lfg_joined": [],
    }

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                """
                SELECT e.title, e.start_ts FROM events e
                JOIN event_rsvps r ON r.guild_id=e.guild_id AND r.message_id=e.message_id
                WHERE e.guild_id=? AND r.user_id=? AND r.response IN ('GOING','MAYBE')
                  AND e.start_ts IS NOT NULL AND e.start_ts > ? AND e.start_ts <= ?
                ORDER BY e.start_ts ASC LIMIT 5
                """,
                (guild_id, user_id, now_ts, cutoff_ts),
            )
            out["events"] = [(str(t or "Event"), int(ts)) for t, ts in await cur.fetchall()]
        except Exception:
            pass

        cur = await db.execute(
            """
            SELECT id, mission_type, channel_id, message_id FROM lfg_posts
            WHERE guild_id=? AND creator_id=? AND status='OPEN'
            ORDER BY created_at DESC LIMIT 3
            """,
            (guild_id, user_id),
        )
        out["lfg_hosting"] = [
            (int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in await cur.fetchall()
        ]

        cur = await db.execute(
            """
            SELECT p.id, p.mission_type, p.channel_id, p.message_id
            FROM lfg_rsvps r
            JOIN lfg_posts p ON p.id = r.lfg_id
            WHERE p.guild_id=? AND r.user_id=? AND r.response='JOIN' AND p.status='OPEN'
              AND p.creator_id != ?
            ORDER BY r.created_at DESC LIMIT 3
            """,
            (guild_id, user_id, user_id),
        )
        out["lfg_joined"] = [
            (int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in await cur.fetchall()
        ]

    return out


def format_schedule_lines(guild_id: int, schedule: dict[str, Any]) -> list[str]:
    """Human-readable lines for embed body or fields."""
    lines: list[str] = []
    for title, start_ts in schedule.get("events") or []:
        lines.append(f"📅 **{title[:40]}** <t:{start_ts}:R>")

    for _id, mission, ch_id, msg_id in schedule.get("lfg_hosting") or []:
        jump = _lfg_jump(guild_id, ch_id, msg_id)
        lines.append(f"🤝 Hosting **{mission}** — [jump to post]({jump})")

    for _id, mission, ch_id, msg_id in schedule.get("lfg_joined") or []:
        jump = _lfg_jump(guild_id, ch_id, msg_id)
        lines.append(f"🤝 Squad **{mission}** — [jump to post]({jump})")

    if schedule.get("events") and not (schedule.get("lfg_hosting") or schedule.get("lfg_joined")):
        lines.append("-# No LFG posted yet — `/lfg` to rally your squad")

    return lines


def schedule_field_block(guild_id: int, schedule: dict[str, Any]) -> tuple[str, str] | None:
    """Return (field_name, field_value) or None when empty."""
    lines = format_schedule_lines(guild_id, schedule)
    if not lines:
        return None
    has_event = bool(schedule.get("events"))
    name = "📅 Your schedule (24h)" if has_event else "🤝 Your squads"
    return name, "\n".join(lines)[:1020]
