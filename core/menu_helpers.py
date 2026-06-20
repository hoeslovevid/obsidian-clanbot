"""Time-aware /menu ordering and onboarding continue hints."""
from __future__ import annotations

from datetime import datetime, timezone

# Indices into MENU_ITEMS in commands/general/menu.py
_MORNING_PRIORITY = {"daily", "claim", "me", "cooldowns", "today"}
_EVENING_PRIORITY = {"lfg", "events", "baro", "fissures", "configure"}


def time_sorted_menu_indices(menu_items: list, *, hour: int | None = None) -> list[int]:
    """Return menu item indices reordered for time of day (favorites/recents unchanged)."""
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    priority = _MORNING_PRIORITY if 5 <= hour < 14 else _EVENING_PRIORITY

    indexed = list(enumerate(menu_items))
    def sort_key(item: tuple[int, tuple]) -> tuple[int, int]:
        idx, row = item
        label, _emoji, path, _hint = row
        slug = (path[-1] if path else label).lower()
        if slug in priority:
            return (0, idx)
        return (1, idx)

    return [i for i, _ in sorted(indexed, key=sort_key)]


async def get_onboarding_continue_hint(guild_id: int, user_id: int) -> str:
    """One-line 'continue setup' blurb for /menu."""
    try:
        from commands.general.onboarding import (
            ONBOARDING_STEP_NAMES,
            get_user_onboarding_progress,
        )

        done, steps = await get_user_onboarding_progress(guild_id, user_id)
        total = len(ONBOARDING_STEP_NAMES)
        if done >= total:
            return ""
        missing = [s for s in ONBOARDING_STEP_NAMES if not steps.get(s)]
        if not missing:
            return ""
        next_step = missing[0].replace("_", " ")
        hints = {
            "set_timezone": "Set timezone in `/preferences`",
            "set_platform": "Set platform in `/preferences`",
            "wf_notify": "Run `/wfnotify configure`",
            "claim_daily": "Claim `/daily`",
            "view_profile": "Open `/profile`",
            "open_wf_hub": "Try `/warframe hub`",
            "use_search": "Try `/search`",
            "view_achievements": "Browse `/achievements`",
        }
        action = hints.get(missing[0], f"Complete **{next_step}**")
        return f"**Continue setup** ({done}/{total}) — {action} · `/onboarding resume`"
    except Exception:
        return ""
