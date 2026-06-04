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


def warframe_footer_platform_note(platform: str, *, pc_only_api: bool = False) -> str:
    """Footer suffix when world-state is PC-sourced but user prefers another platform."""
    p = (platform or "pc").strip().lower()
    if pc_only_api and p != "pc":
        return f"World-state data is PC-only · your pref is {p.upper()}"
    if p != "pc":
        return f"Platform: {p.upper()} · some feeds are PC-sourced"
    return "Platform: PC"
