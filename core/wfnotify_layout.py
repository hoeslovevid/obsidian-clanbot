"""Components V2 wfnotify configure opening screen."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_WARFRAME, footer_display, make_container


class WfNotifyConfigureLayout(ui.LayoutView):
    """MVP opening screen for /wfnotify setup (configure wizard)."""

    def __init__(
        self,
        *,
        overview_text: str,
        on_pick: Optional[Callable[[discord.Interaction, str], Awaitable[None]]] = None,
        categories: Optional[list[tuple[str, str]]] = None,
    ):
        super().__init__(timeout=300)
        lines = ["## 🔔 Warframe Notify Setup", "", overview_text.strip(), "", footer_display("warframe_notify")]
        self.add_item(make_container(lines, accent=ACCENT_WARFRAME))
        if on_pick and categories:
            options = [
                discord.SelectOption(label=label.split(" ", 1)[-1][:100], value=slug, emoji=label.split(" ", 1)[0])
                for slug, label in categories[:25]
            ]
            if options:
                row = ui.ActionRow()
                sel = ui.Select(placeholder="Pick a notification stream…", options=options, min_values=1, max_values=1)

                async def _cb(inter: discord.Interaction):
                    await on_pick(inter, sel.values[0])

                sel.callback = _cb  # type: ignore[assignment]
                row.add_item(sel)
                self.add_item(row)
