"""Components V2 /daily layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_ECONOMY, compact_fields, footer_display, make_container


class DailyLayout(ui.LayoutView):
    def __init__(self, *, title: str, description: str, fields: list[tuple[str, str, bool]]):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", description.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("economy_daily")])
        self.add_item(make_container(lines, accent=ACCENT_ECONOMY))
