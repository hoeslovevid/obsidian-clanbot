"""Components V2 /whatsnew layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, make_container
from core.utils import bullet_list


class WhatsNewLayout(ui.LayoutView):
    def __init__(
        self,
        *,
        version: str,
        date: str,
        changes: list[str],
        page: int,
        total_pages: int,
        subscribed: bool,
        on_prev: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_next: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        on_subscribe: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=300)
        header = f"Released {date}" if date else "Recent changes"
        lines = [
            f"## 📝 What's New • v{version}",
            "",
            f"_{header}_",
            "",
            bullet_list([str(c) for c in changes[:25]]),
            "",
            f"-# Page {page + 1}/{total_pages}",
        ]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        row = ui.ActionRow()
        if on_prev:
            prev = ui.Button(label="◀ Older", style=discord.ButtonStyle.secondary, disabled=page >= total_pages - 1)
            prev.callback = lambda i: on_prev(i)  # type: ignore[assignment]
            row.add_item(prev)
        if on_next:
            nxt = ui.Button(label="Newer ▶", style=discord.ButtonStyle.secondary, disabled=page <= 0)
            nxt.callback = lambda i: on_next(i)  # type: ignore[assignment]
            row.add_item(nxt)
        if on_subscribe:
            label = "🔕 Unsubscribe DMs" if subscribed else "🔔 Subscribe DMs"
            style = discord.ButtonStyle.secondary if subscribed else discord.ButtonStyle.primary
            sub = ui.Button(label=label, style=style)
            sub.callback = lambda i: on_subscribe(i)  # type: ignore[assignment]
            row.add_item(sub)
        if row.children:
            self.add_item(row)
