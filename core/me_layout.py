"""Components V2 /me layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, compact_fields, footer_display, make_container


class MeLayout(ui.LayoutView):
    def __init__(self, *, title: str, intro: str, fields: list[tuple[str, str, bool]], footer: str):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", f"-# {footer}"])
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
