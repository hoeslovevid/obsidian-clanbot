"""Post-command 'what next?' hints for high-traffic flows."""
from __future__ import annotations

# context -> ordered preference keys checked via onboarding progress
_NEXT_BY_CONTEXT: dict[str, list[tuple[str, str]]] = {
    "daily": [
        ("claim_daily", "Try **`/claim`** for bounties"),
        ("open_menu", "Open **`/menu`** for more"),
        ("wf_notify", "Set alerts with **`/wfnotify configure`**"),
    ],
    "claim": [
        ("claim_daily", "Don't forget **`/daily`**"),
        ("view_profile", "See progress on **`/profile`**"),
        ("open_menu", "**`/menu`** has quick picks"),
    ],
    "lfg": [
        ("wf_notify", "Get cycle alerts — **`/wfnotify configure`**"),
        ("open_wf_hub", "Check **`/warframe hub`**"),
        ("open_menu", "**`/menu`** · **`/search lfg`**"),
    ],
    "ticket": [
        ("browse_help", "Browse **`/help`** while you wait"),
        ("open_menu", "**`/menu`** for other tools"),
    ],
}


async def get_next_step_hint(guild_id: int, user_id: int, context: str) -> str:
    """One-line footer hint after a command, or empty string."""
    steps = _NEXT_BY_CONTEXT.get(context)
    if not steps:
        return ""
    try:
        from commands.general.onboarding import (
            ONBOARDING_STEP_NAMES,
            get_user_onboarding_progress,
        )

        done, progress = await get_user_onboarding_progress(guild_id, user_id)
        if done >= len(ONBOARDING_STEP_NAMES):
            return "Next: **`/today`** · **`/menu`** · **`/notifications`**"
        for key, hint in steps:
            if not progress.get(key):
                return f"Next: {hint}"
        return "Next: **`/today`** · **`/notifications`**"
    except Exception:
        return "Next: **`/menu`** · **`/help`**"
