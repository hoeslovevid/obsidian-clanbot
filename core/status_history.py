"""Record and surface brief operational status history (WF API, maintenance)."""
from __future__ import annotations

from database import get_guild_setting, set_guild_setting, now_utc


async def record_wf_status(degraded: bool, detail: str = "") -> None:
    """Store last WF API state globally (guild_id=0)."""
    ts = now_utc().isoformat()
    state = "degraded" if degraded else "ok"
    await set_guild_setting(0, "global_wf_status", state)
    await set_guild_setting(0, "global_wf_status_at", ts)
    if detail:
        await set_guild_setting(0, "global_wf_status_detail", detail[:200])


async def wf_status_history_line() -> str | None:
    """One-line history for /status."""
    state = await get_guild_setting(0, "global_wf_status")
    at = await get_guild_setting(0, "global_wf_status_at")
    if not state or not at:
        return None
    if state == "ok":
        return f"_Last WF API check: operational (<t:{_ts(at)}:R>)_"
    detail = await get_guild_setting(0, "global_wf_status_detail") or "degraded"
    return f"_Last WF API issue: {detail} (<t:{_ts(at)}:R>)_"


def _ts(iso: str) -> int:
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0
