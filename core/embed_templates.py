"""Embed template presets built on obsidian_embed()."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import discord  # type: ignore

from core.embed_assets import (
    CATEGORY_THUMBNAILS,
    COMPLAINT_SEVERITY_COLORS,
    PLATFORM_EMOJI,
    TEMPLATE_IMAGES,
    WARFRAME_VARIANT_THUMBNAILS,
)
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
        thumbnail = thumbnail or CATEGORY_THUMBNAILS.get(cat)
    elif template == "warframe_status":
        cat = "warframe"
        if variant and variant in WARFRAME_VARIANT_THUMBNAILS:
            thumbnail = thumbnail or WARFRAME_VARIANT_THUMBNAILS[variant]
        else:
            thumbnail = thumbnail or CATEGORY_THUMBNAILS.get("warframe")
        if platform and platform in PLATFORM_EMOJI:
            title = f"{PLATFORM_EMOJI[platform]} {title}"
    elif template == "profile":
        cat = kwargs.pop("profile_category", "general") or "general"
    elif template == "error":
        cat = "error"
        image = image or TEMPLATE_IMAGES.get("error")
        thumbnail = thumbnail or CATEGORY_THUMBNAILS.get("error")
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
    base_footer = footer or "Use /help for commands"
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
