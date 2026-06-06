"""Components V2 music now-playing panel."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_MUSIC, footer_display, make_container


class MusicPanelLayout(ui.LayoutView):
    """Now Playing panel with Skip / Pause / Queue on ActionRow."""

    def __init__(
        self,
        *,
        guild_id: int,
        title: str,
        body: str,
        on_skip: Callable[[discord.Interaction], Awaitable[None]],
        on_toggle: Callable[[discord.Interaction], Awaitable[None]],
        on_queue: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=None)
        lines = [f"## {title}", "", body.strip(), "", footer_display("music")]
        self.add_item(make_container(lines, accent=ACCENT_MUSIC, banner=False))
        row = ui.ActionRow()
        skip = ui.Button(label="Skip", style=discord.ButtonStyle.primary, custom_id=f"music:{guild_id}:skip")
        skip.callback = lambda i: on_skip(i)  # type: ignore[assignment]
        toggle = ui.Button(label="Pause", style=discord.ButtonStyle.secondary, custom_id=f"music:{guild_id}:toggle")
        toggle.callback = lambda i: on_toggle(i)  # type: ignore[assignment]
        queue = ui.Button(label="Queue", style=discord.ButtonStyle.secondary, custom_id=f"music:{guild_id}:queue")
        queue.callback = lambda i: on_queue(i)  # type: ignore[assignment]
        row.add_item(skip)
        row.add_item(toggle)
        row.add_item(queue)
        self.add_item(row)
