"""Components V2 compact layouts for /about, /recent, /favorites."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, compact_fields, make_container


class AboutLayout(ui.LayoutView):
    def __init__(self, *, title: str, intro: str, fields: list[tuple[str, str, bool]]):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))


class RecentLayout(ui.LayoutView):
    def __init__(self, *, body: str):
        super().__init__(timeout=120)
        lines = ["## 🕐 Recent Commands", "", body.strip(), "", "-# Tap a command in chat or use /menu"]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))


class FavoritesLayout(ui.LayoutView):
    def __init__(self, *, body: str, slots_used: int, max_slots: int):
        super().__init__(timeout=120)
        lines = [
            "## ⭐ Your Favorites",
            "",
            body.strip(),
            "",
            f"-# {slots_used}/{max_slots} slots · /favorite_add to pin more",
        ]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
