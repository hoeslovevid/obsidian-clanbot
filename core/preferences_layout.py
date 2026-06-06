"""Components V2 /preferences summary layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, make_container


class PreferencesLayout(ui.LayoutView):
    def __init__(self, *, lines: list[str]):
        super().__init__(timeout=120)
        body = ["## ⚙️ Preferences", ""] + lines + ["", "-# Run /preferences with options to change settings"]
        self.add_item(make_container(body, accent=ACCENT_DEFAULT))
