"""Bot presence (sidebar activity) and website display helpers."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

import discord  # type: ignore

from core.config import BOT_WEBSITE


def website_host() -> Optional[str]:
    """Return a short hostname for presence/footer text (e.g. obsidianoverseer.com)."""
    if not BOT_WEBSITE:
        return None
    raw = BOT_WEBSITE.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def build_bot_activity(bot) -> discord.Activity:
    """Presence shown in the member list: website + /help + guild count."""
    guild_count = len(getattr(bot, "guilds", []) or [])
    servers = f"{guild_count} server{'s' if guild_count != 1 else ''}"
    host = website_host()
    if host:
        name = f"{host} • /help • {servers}"
    else:
        name = f"/help • {servers}"
    return discord.Activity(
        type=discord.ActivityType.watching,
        name=name[:128],
    )
