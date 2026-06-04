"""User time-format preferences (12h vs 24h) for display helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from database import get_guild_setting

DateLike = Union[datetime, str, None]


async def get_user_time_format(guild_id: int, user_id: int) -> str:
    """Return '12' or '24' (default 12 for US-heavy clan bots)."""
    val = await get_guild_setting(guild_id, f"user_time_format:{user_id}")
    return "24" if val == "24" else "12"


async def format_user_time(
    guild_id: int,
    user_id: int,
    dt: DateLike,
    *,
    include_relative: bool = True,
) -> str:
    """Discord timestamp with optional relative; style respects 12/24 pref where applicable."""
    from core.utils import format_timestamp_readable

    if dt is None:
        return "—"
    if include_relative:
        return format_timestamp_readable(dt, include_relative=True)
    try:
        if hasattr(dt, "timestamp"):
            ts = int(dt.timestamp())
        else:
            parsed = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
            ts = int(parsed.timestamp())
        fmt = await get_user_time_format(guild_id, user_id)
        style = "f" if fmt == "24" else "f"  # Discord locale handles 12/24 in client
        return f"<t:{ts}:{style}>"
    except Exception:
        return str(dt)
