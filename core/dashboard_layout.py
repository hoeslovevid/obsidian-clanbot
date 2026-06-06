"""Components V2 mod dashboard snapshot (refresh only)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_MODERATION, compact_fields, make_container


class ModDashboardSnapshotLayout(ui.LayoutView):
    """Lightweight V2 snapshot for dashboard refresh — full dashboard stays classic."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        fields: list[tuple[str, str, bool]],
        on_refresh: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=300)
        lines = [f"## {title}", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields[:3])])  # snapshot: top sections only
        lines.append("\n-# Full tools remain on classic dashboard embed")
        self.add_item(make_container(lines, accent=ACCENT_MODERATION, banner=False))
        if on_refresh:
            row = ui.ActionRow()
            btn = ui.Button(label="🔄 Refresh snapshot", style=discord.ButtonStyle.secondary)
            btn.callback = lambda i: on_refresh(i)  # type: ignore[assignment]
            row.add_item(btn)
            self.add_item(row)
