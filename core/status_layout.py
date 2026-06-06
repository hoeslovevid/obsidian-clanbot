"""Components V2 /status layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, ACCENT_WARNING, footer_display, make_container


class StatusLayout(ui.LayoutView):
    def __init__(
        self,
        *,
        title: str,
        body: str,
        version: str,
        degraded: bool = False,
    ):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", body.strip(), "", footer_display("status", version=version)]
        accent = ACCENT_WARNING if degraded else ACCENT_DEFAULT
        self.add_item(make_container(lines, accent=accent))
