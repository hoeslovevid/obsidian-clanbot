"""Leaderboard privacy helpers (QoL #13)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import discord

HIDDEN_LABEL = "🕵️ Hidden"
_SETTING_KEY = "user_hide_leaderboards:{user_id}"


async def user_hides_from_leaderboards(guild_id: int, user_id: int) -> bool:
    from database import get_guild_setting

    return (await get_guild_setting(guild_id, _SETTING_KEY.format(user_id=user_id))) == "1"


async def leaderboard_display_name(
    guild: "discord.Guild",
    user_id: int,
    *,
    fallback: Optional[str] = None,
) -> str:
    """Return a leaderboard-safe display name, respecting privacy opt-out."""
    if await user_hides_from_leaderboards(guild.id, user_id):
        return HIDDEN_LABEL
    member = guild.get_member(user_id)
    if member:
        return member.display_name
    return fallback or f"User {user_id}"
