"""Components V2 profile layout (HELP_LAYOUT_V2 gate)."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE
from core.help_layout import help_layout_v2_enabled
from core.layout_v2 import ACCENT_DEFAULT, compact_fields, footer_display, make_container
from core.presence import website_host


def profile_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class ProfileFullLayout(ui.LayoutView):
    """Full profile card in V2 — single-message self-view."""

    def __init__(
        self,
        *,
        title: str,
        description: str,
        fields: list[tuple[str, str, bool]],
        footer_key: str = "profile",
    ):
        super().__init__(timeout=120)
        lines = [f"## {title}"]
        if description.strip():
            lines.extend(["", description.strip()])
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display(footer_key)])
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        if BOT_WEBSITE:
            row = ui.ActionRow()
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
            self.add_item(row)


class ProfileSnapshotLayout(ProfileFullLayout):
    """Back-compat compact profile splash."""

    def __init__(
        self,
        *,
        display_name: str,
        headline: str,
        stats_blurb: str,
        avatar_url: Optional[str] = None,
    ):
        super().__init__(
            title=display_name,
            description=f"{headline.strip()}\n\n{stats_blurb.strip()}",
            fields=[],
            footer_key="profile",
        )
