"""Embed template presets built on obsidian_embed()."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import discord  # type: ignore

from core.embed_assets import (
    CATEGORY_THUMBNAILS,
    category_thumbnail,
    COMPLAINT_SEVERITY_COLORS,
    PLATFORM_EMOJI,
    TEMPLATE_IMAGES,
    TICKET_PRIORITY_COLORS,
    TICKET_STATUS_COLORS,
    WARFRAME_VARIANT_THUMBNAILS,
)
from core.embed_footers import footer_for
from core.utils import EMBED_COLORS, obsidian_embed


def _cached_footer_suffix(cached_at: Optional[datetime]) -> str:
    if not cached_at:
        return ""
    age = (datetime.now(timezone.utc) - cached_at).total_seconds()
    if age < 60:
        return f" · Cached · {int(age)}s ago"
    return f" · Cached · {int(age // 60)}m ago"


def embed_template(
    template: str,
    title: str,
    desc: str = "",
    *,
    category: Optional[str] = None,
    variant: Optional[str] = None,
    client=None,
    cached_at: Optional[datetime] = None,
    error_code: Optional[str] = None,
    platform: Optional[str] = None,
    severity: Optional[str] = None,
    brand: bool = False,
    **kwargs: Any,
) -> discord.Embed:
    """Build an embed from a named template preset."""
    cat = category or "general"
    thumbnail = kwargs.pop("thumbnail", None)
    image = kwargs.pop("image", None)
    footer = kwargs.pop("footer", None)

    if template == "showcase":
        brand = True
        image = image or TEMPLATE_IMAGES.get("showcase")
        thumbnail = thumbnail or category_thumbnail(cat)
    elif template == "warframe_status":
        cat = "warframe"
        if variant and variant in WARFRAME_VARIANT_THUMBNAILS:
            thumbnail = thumbnail or WARFRAME_VARIANT_THUMBNAILS[variant]
        else:
            thumbnail = thumbnail or category_thumbnail("warframe")
        if platform and platform in PLATFORM_EMOJI:
            title = f"{PLATFORM_EMOJI[platform]} {title}"
    elif template == "profile":
        cat = kwargs.pop("profile_category", "general") or "general"
    elif template == "warning":
        cat = category or "warning"
        thumbnail = thumbnail or category_thumbnail("warning")
        if color is None and "color" not in kwargs:
            kwargs["color"] = EMBED_COLORS.get("warning")
    elif template == "error":
        cat = "error"
        image = image or TEMPLATE_IMAGES.get("error")
        thumbnail = thumbnail or category_thumbnail("error")
    elif template == "levelup":
        cat = "prestige"
        level = int(variant or "1")
        if level >= 50:
            image = image or TEMPLATE_IMAGES.get("levelup_high")
        elif level >= 20:
            image = image or TEMPLATE_IMAGES.get("levelup_mid")
        else:
            image = image or TEMPLATE_IMAGES.get("levelup_low")
        brand = True
    elif template == "complaint":
        cat = "moderation"
        if severity and severity in COMPLAINT_SEVERITY_COLORS:
            kwargs["color"] = discord.Color.from_str(COMPLAINT_SEVERITY_COLORS[severity])

    cache_suffix = _cached_footer_suffix(cached_at)
    base_footer = footer or footer_for("default")
    if error_code:
        base_footer = f"{base_footer} · Code: {error_code}"
    if cache_suffix:
        base_footer = f"{base_footer}{cache_suffix}"

    return obsidian_embed(
        title,
        desc,
        category=cat,
        thumbnail=thumbnail,
        image=image,
        footer=base_footer,
        client=client,
        brand=brand,
        **kwargs,
    )


def help_breadcrumb(group_path: list[str], command_name: Optional[str] = None) -> str:
    """Format help title breadcrumb: warframe › baro."""
    parts = group_path + ([command_name] if command_name else [])
    return " › ".join(parts)


def complaint_case_embed(
    title: str,
    desc: str,
    category: str,
    *,
    client=None,
    **kwargs: Any,
) -> discord.Embed:
    """Build a docket/complaint embed with severity color from category."""
    from core.embed_assets import complaint_severity_for_category

    severity = complaint_severity_for_category(category)
    return embed_template(
        "complaint",
        title,
        desc,
        severity=severity,
        client=client,
        **kwargs,
    )


def confirm_embed(
    title: str,
    desc: str,
    *,
    client=None,
    footer: Optional[str] = None,
    footer_key: str = "moderation_purge",
    **kwargs: Any,
) -> discord.Embed:
    """Consistent confirmation / destructive-action embed (warning styling)."""
    return embed_template(
        "warning",
        title,
        desc,
        category="moderation",
        footer=footer or footer_for(footer_key),
        client=client,
        **kwargs,
    )


TICKET_STATUS_LABELS: dict[str, str] = {
    "open": "Open",
    "awaiting_staff": "Awaiting staff",
    "awaiting_member": "Awaiting member",
    "closed": "Closed",
}


def ticket_status_chip(status: str) -> str:
    """Human-readable status chip for ticket titles/footers."""
    key = (status or "open").strip().lower()
    return TICKET_STATUS_LABELS.get(key, key.replace("_", " ").title())


def ticket_embed(
    title: str,
    desc: str,
    *,
    status: str = "open",
    priority: str = "normal",
    client=None,
    **kwargs: Any,
) -> discord.Embed:
    """Ticket channel / confirmation embed with status and priority colors."""
    status_key = (status or "open").strip().lower()
    chip = ticket_status_chip(status_key)
    if chip.lower() not in title.lower():
        title = f"{title} · {chip}"
    priority_key = (priority or "normal").strip().lower()
    if priority_key == "urgent" and status_key == "open":
        color = discord.Color.from_str(TICKET_PRIORITY_COLORS["urgent"])
    else:
        color = discord.Color.from_str(
            TICKET_STATUS_COLORS.get(status_key, TICKET_STATUS_COLORS["open"])
        )
    footer = kwargs.pop("footer", None)
    if footer and chip.lower() not in str(footer).lower():
        footer = f"{chip} · {footer}"
    elif not footer:
        footer = chip

    return obsidian_embed(
        title,
        desc,
        category="community",
        color=color,
        footer=footer,
        client=client,
        **kwargs,
    )
