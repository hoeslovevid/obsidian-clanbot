"""Optional per-guild embed footer suffix for mods."""
from __future__ import annotations

from database import get_guild_setting, set_guild_setting

_footer_cache: dict[int, str | None] = {}


async def get_guild_embed_footer(guild_id: int) -> str | None:
    raw = await get_guild_setting(guild_id, "guild_embed_footer")
    if raw and str(raw).strip():
        result = str(raw).strip()[:120]
    else:
        result = None
    _footer_cache[guild_id] = result
    return result


async def set_guild_embed_footer(guild_id: int, text: str | None) -> None:
    if not text or not str(text).strip():
        await set_guild_setting(guild_id, "guild_embed_footer", "")
        _footer_cache[guild_id] = None
        return
    value = str(text).strip()[:120]
    await set_guild_setting(guild_id, "guild_embed_footer", value)
    _footer_cache[guild_id] = value


def cached_guild_footer(guild_id: int | None) -> str | None:
    """Best-effort sync read (populated by get/set or first embed in guild)."""
    if guild_id is None:
        return None
    return _footer_cache.get(guild_id)


def merge_guild_footer(base: str, suffix: str | None) -> str:
    if not suffix:
        return base
    if not base:
        return suffix
    return f"{base} · {suffix}"
