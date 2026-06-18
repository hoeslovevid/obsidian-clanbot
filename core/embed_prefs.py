"""Per-user embed display options (compact mode, etc.)."""
from __future__ import annotations


async def embed_kwargs(guild_id: int, user_id: int) -> dict:
    """Kwargs to pass into ``obsidian_embed(..., **embed_kwargs(...))``."""
    from core.user_prefs import compact_embeds

    return {"compact": await compact_embeds(guild_id, user_id)}
