"""Small helpers for per-user command preferences."""
from __future__ import annotations


async def results_ephemeral(guild_id: int, user_id: int, default: bool = False) -> bool:
    """Whether the user prefers personal command results delivered privately.

    Controlled by ``/preferences private_results``. Returns ``default`` when the
    user has never set the preference.
    """
    try:
        from database import get_guild_setting

        val = await get_guild_setting(guild_id, f"user_private_results:{user_id}")
    except Exception:
        return default
    if val is None:
        return default
    return str(val) == "1"


async def compact_embeds(guild_id: int, user_id: int) -> bool:
    """Whether the user prefers shorter embeds (no timestamp, tighter spacing)."""
    try:
        from database import get_guild_setting

        val = await get_guild_setting(guild_id, f"user_compact_embeds:{user_id}")
    except Exception:
        return False
    return str(val) == "1"


async def default_fissure_tier(guild_id: int, user_id: int) -> str | None:
    """Saved default fissure tier filter (Lith, Meso, etc.) or None for all."""
    try:
        from database import get_guild_setting

        val = await get_guild_setting(guild_id, f"user_fissure_tier:{user_id}")
    except Exception:
        return None
    if not val or str(val).lower() in ("all", "-", "off"):
        return None
    return str(val)
