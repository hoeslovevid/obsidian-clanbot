"""Bot presence (sidebar activity) and website display helpers."""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

import discord  # type: ignore

from core.config import BOT_VERSION, BOT_WEBSITE


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


def _warframe_health_snippet() -> tuple[str, bool]:
    try:
        from core.cache_utils import warframe_health_line

        line, degraded = warframe_health_line()
        if not line:
            return "", False
        short = line.replace("Warframe API:", "").replace("**", "").strip()
        if len(short) > 36:
            short = short[:33] + "…"
        return (f"WF {'degraded' if degraded else 'ok'}" if not short else short), degraded
    except Exception:
        return "", False


def _presence_mode() -> str:
    """Rotation mode: default | menu | degraded | event (env PRESENCE_MODE)."""
    return (os.getenv("PRESENCE_MODE", "default") or "default").strip().lower()


def build_bot_activity(bot) -> discord.Activity:
    """Presence: version, optional API health hint, /help, guild count.

    ``PRESENCE_MODE`` env:
    - ``menu`` — emphasize /menu discovery
    - ``degraded`` — surface WF API health when degraded
    - ``event`` — highlight /events
    - ``default`` — balanced mix
    """
    guild_count = len(getattr(bot, "guilds", []) or [])
    servers = f"{guild_count} srv" if guild_count else ""
    version = (getattr(bot, "_bot_version", None) or BOT_VERSION or "").strip()
    mode = _presence_mode()
    parts: list[str] = []
    if version:
        parts.append(f"v{version}")

    health, degraded = _warframe_health_snippet()
    if mode == "degraded" and degraded:
        parts.append(health or "WF degraded")
    elif mode == "menu":
        parts.append("/menu")
    elif mode == "event":
        parts.append("/events")
    else:
        if health and degraded:
            parts.append(health)
        host = website_host()
        if host:
            parts.append(host)
        parts.append("/help")

    if servers and mode != "menu":
        parts.append(servers)
    name = " · ".join(p for p in parts if p)[:128]
    return discord.Activity(type=discord.ActivityType.watching, name=name)
