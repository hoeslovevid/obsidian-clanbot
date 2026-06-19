"""One-time discovery hint for users running economy/Warframe commands."""
from __future__ import annotations

from database import get_guild_setting, set_guild_setting

_FEATURE_HINTS: dict[str, str] = {
    "general": "Try {search} or {onboard} to get oriented.",
    "daily": "Pin favorites with `/favorite_add` — try {claim} for a full claim overview.",
    "baro": "Set a default fissure tier in `/general preferences` — use {search} to find more commands.",
    "ticket": "Check case status anytime with `/case`.",
    "trade": "Look up prices with `/trading trade_price` or set `/price_watch`.",
    "lfg": "Browse open posts with `/lfg_list` when you're ready to squad up.",
    "event": "RSVP buttons on the event post track who's going — creators can tap **+15m late** if needed.",
    "price_watch": "List watches with `/price_watches` — DMs respect your quiet hours.",
    "preferences": "Set timezone and quiet hours so digests and reminders land at the right time.",
    "wfnotify": "One setup covers Baro, fissures, alerts, and more — try {search} for other WF commands.",
    "achievements": "Unlock badges over time — your profile shows equipped ones.",
}


async def maybe_first_run_hint(
    guild_id: int,
    user_id: int,
    body: str,
    *,
    feature: str = "general",
) -> str:
    """Append a single onboarding hint the first time a user runs a featured command."""
    key = f"user_seen_intro:{feature}:{user_id}"
    if await get_guild_setting(guild_id, key):
        return body
    await set_guild_setting(guild_id, key, "1")
    from core.command_mentions import command_mention

    search = command_mention("search", fallback="`/search`")
    onboard = command_mention("onboarding", fallback="`/onboarding`")
    claim = command_mention("claim", fallback="`/claim`")
    recent = command_mention("recent", fallback="`/recent`")
    template = _FEATURE_HINTS.get(feature, _FEATURE_HINTS["general"])
    hint = template.format(search=search, onboard=onboard, claim=claim, recent=recent)
    return f"{body}\n-# 💡 New here? {hint}"
