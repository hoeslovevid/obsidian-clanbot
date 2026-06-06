"""Shared Discord Components V2 (LayoutView) helpers."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.embed_assets import EMBED_BANNER_URL
from core.embed_footers import footer_for
from core.config import HELP_LAYOUT_V2

ACCENT_DEFAULT = "#7C83FF"
ACCENT_ECONOMY = "#F0A800"
ACCENT_WARFRAME = "#00B894"
ACCENT_COMMUNITY = "#7C83FF"
ACCENT_MODERATION = "#E74C3C"
ACCENT_WARNING = "#E67E22"
ACCENT_MUSIC = "#9B59B6"


def v2_enabled() -> bool:
    return HELP_LAYOUT_V2


def footer_display(key: str, *, default: Optional[str] = None, **fmt: object) -> str:
    return f"-# {footer_for(key, default=default, **fmt)}"


def make_container(
    lines: list[str],
    *,
    accent: str = ACCENT_DEFAULT,
    banner: bool = True,
) -> ui.Container:
    container = ui.Container(
        ui.TextDisplay(content="\n".join(lines)),
        accent_color=discord.Color.from_str(accent),
    )
    if banner and EMBED_BANNER_URL:
        try:
            container.add_item(ui.MediaGallery(discord.UnfurledMediaItem(url=EMBED_BANNER_URL)))
        except Exception:
            pass
    return container


def compact_fields(fields: list[tuple[str, str, bool]], *, max_len: int = 3500) -> str:
    """Turn embed-style fields into markdown blocks for TextDisplay."""
    parts: list[str] = []
    for name, value, _inline in fields:
        block = f"**{name}**\n{value.strip()}"
        test = "\n\n".join(parts + [block])
        if len(test) > max_len:
            parts.append(f"\n_…{len(fields) - len(parts)} more section(s)_")
            break
        parts.append(block)
    return "\n\n".join(parts)
