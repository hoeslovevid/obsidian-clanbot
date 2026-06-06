"""Components V2 LFG post panel."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_COMMUNITY, compact_fields, footer_display, make_container


class LFGPanelLayout(ui.LayoutView):
    """LFG post with Join / Leave / Filled / Squad radio buttons."""

    def __init__(
        self,
        *,
        lfg_id: int,
        intro: str,
        fields: list[tuple[str, str, bool]],
        on_join: Callable[[discord.Interaction], Awaitable[None]],
        on_leave: Callable[[discord.Interaction], Awaitable[None]],
        on_filled: Callable[[discord.Interaction], Awaitable[None]],
        on_radio: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=None)
        lines = ["## 🔍 Looking for Group", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("community_lfg")])
        self.add_item(make_container(lines, accent=ACCENT_COMMUNITY, banner=False))
        row0 = ui.ActionRow()
        for label, style, emoji, cb, cid in (
            ("Join", discord.ButtonStyle.success, "✅", on_join, f"lfg:{lfg_id}:join"),
            ("Leave", discord.ButtonStyle.danger, "❌", on_leave, f"lfg:{lfg_id}:leave"),
            ("Mark as Filled", discord.ButtonStyle.primary, "✅", on_filled, f"lfg:{lfg_id}:complete"),
        ):
            btn = ui.Button(label=label, style=style, emoji=emoji, custom_id=cid)
            btn.callback = lambda i, fn=cb: fn(i)  # type: ignore[assignment]
            row0.add_item(btn)
        self.add_item(row0)
        if on_radio:
            row1 = ui.ActionRow()
            radio = ui.Button(
                label="Start squad radio",
                style=discord.ButtonStyle.secondary,
                emoji="🎵",
                custom_id=f"lfg:{lfg_id}:radio",
            )
            radio.callback = lambda i: on_radio(i)  # type: ignore[assignment]
            row1.add_item(radio)
            self.add_item(row1)
