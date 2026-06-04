"""Resolve Warframe API platform from user preferences."""
from __future__ import annotations

from database import get_user_platform

_VALID = frozenset({"pc", "xbox", "ps4", "switch"})


async def resolve_warframe_platform(guild_id: int, user_id: int) -> str:
    """User platform pref, else PC (warframestat.us paths use pc/xbox/ps4/switch)."""
    raw = await get_user_platform(guild_id, user_id)
    if raw:
        p = raw.strip().lower()
        if p in _VALID:
            return p
    return "pc"
