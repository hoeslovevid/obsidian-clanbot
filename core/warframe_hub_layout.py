"""Components V2 /warframe hub layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_WARFRAME, compact_fields, footer_display, make_container


class WarframeHubLayout(ui.LayoutView):
    def __init__(
        self,
        *,
        title: str,
        intro: str,
        fields: list[tuple[str, str, bool]],
        on_refresh: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        extra_buttons: Optional[list[ui.Button]] = None,
    ):
        super().__init__(timeout=300)
        lines = [f"## {title}", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("warframe_hub")])
        self.add_item(make_container(lines, accent=ACCENT_WARFRAME))
        if on_refresh or extra_buttons:
            row = ui.ActionRow()
            if on_refresh:
                btn = ui.Button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
                btn.callback = lambda i: on_refresh(i)  # type: ignore[assignment]
                row.add_item(btn)
            for b in extra_buttons or []:
                row.add_item(b)
            if row.children:
                self.add_item(row)
