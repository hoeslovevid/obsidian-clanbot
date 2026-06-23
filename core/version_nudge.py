"""Once-per-version 'what's new' blurb for /menu and /help."""
from __future__ import annotations

from core.changelog import get_latest_changelog_entry
from core.config import BOT_VERSION
from database import get_guild_setting, set_guild_setting


def _seen_key(user_id: int, *, surface: str) -> str:
    return f"seen_version_{surface}:{user_id}"


async def build_whats_new_blurb(
    guild_id: int,
    user_id: int,
    *,
    surface: str = "menu",
    mark_seen: bool = True,
) -> str:
    """Return a short changelog blurb the first time a user opens a surface this version."""
    try:
        key = _seen_key(user_id, surface=surface)
        last_ver = await get_guild_setting(guild_id, key) or ""
        if last_ver == BOT_VERSION:
            return ""
        entry = get_latest_changelog_entry()
        bullets = entry.get("changes") or []
        if not bullets:
            if mark_seen:
                await set_guild_setting(guild_id, key, BOT_VERSION)
            return ""
        blurb = (
            f"**What's new in v{BOT_VERSION}** — "
            + " · ".join(str(b)[:90] for b in bullets[:3])
            + "\n_Full notes: `/whatsnew`_\n\n"
        )
        if mark_seen:
            await set_guild_setting(guild_id, key, BOT_VERSION)
        return blurb
    except Exception:
        return ""
