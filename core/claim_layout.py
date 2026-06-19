"""Components V2 /claim hub layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_ECONOMY, footer_display, make_container


class ClaimLayout(ui.LayoutView):
    def __init__(
        self,
        *,
        body: str,
        on_bounties: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_invest: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_daily: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=120)
        lines = ["## 💰 Claim Hub", "", body.strip(), "", footer_display("claim")]
        self.add_item(make_container(lines, accent=ACCENT_ECONOMY, banner=False))
        if on_bounties or on_invest or on_daily:
            row = ui.ActionRow()
            if on_bounties:
                b = ui.Button(label="Claim bounties", emoji="🎯", style=discord.ButtonStyle.success)
                b.callback = lambda i: on_bounties(i)  # type: ignore[assignment]
                row.add_item(b)
            if on_invest:
                b = ui.Button(label="Collect investment", emoji="📈", style=discord.ButtonStyle.primary)
                b.callback = lambda i: on_invest(i)  # type: ignore[assignment]
                row.add_item(b)
            if on_daily:
                b = ui.Button(label="Run daily", emoji="🎁", style=discord.ButtonStyle.secondary)
                b.callback = lambda i: on_daily(i)  # type: ignore[assignment]
                row.add_item(b)
            self.add_item(row)
