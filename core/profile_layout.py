"""Components V2 profile layout pilot (HELP_LAYOUT_V2 gate)."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE
from core.embed_assets import EMBED_BANNER_URL
from core.help_layout import help_layout_v2_enabled
from core.presence import website_host


def profile_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class ProfileSnapshotLayout(ui.LayoutView):
    """Compact V2 profile splash; classic embed remains the full card."""

    def __init__(
        self,
        *,
        display_name: str,
        headline: str,
        stats_blurb: str,
        avatar_url: Optional[str] = None,
    ):
        super().__init__(timeout=120)
        lines = [
            f"## {display_name}",
            "",
            headline.strip(),
            "",
            stats_blurb.strip(),
            "",
            "-# `/profile` for full card · `/achievements` for badges · `/wallet` for coins",
        ]
        container = ui.Container(
            ui.TextDisplay(content="\n".join(lines)),
            accent_color=discord.Color.from_str("#7C83FF"),
        )
        if EMBED_BANNER_URL:
            try:
                container.add_item(
                    ui.MediaGallery(discord.UnfurledMediaItem(url=EMBED_BANNER_URL))
                )
            except Exception:
                pass
        self.add_item(container)
        if BOT_WEBSITE:
            row = ui.ActionRow()
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
            self.add_item(row)
