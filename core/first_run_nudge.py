"""One-time discovery hint for users running economy/Warframe commands."""
from __future__ import annotations

from database import get_guild_setting, set_guild_setting


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
    return f"{body}\n-# 💡 New here? Try {search} or {onboard} to get oriented."
