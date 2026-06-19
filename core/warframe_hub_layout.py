"""Components V2 Warframe hub layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE
from core.layout_v2 import ACCENT_WARFRAME, compact_fields, footer_display, make_container
from core.presence import website_host


class WarframeHubLayout(ui.LayoutView):
    """Refreshable Warframe dashboard — Layout v2."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        fields: list[tuple[str, str, bool]],
        on_refresh: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
        guild_id: int = 0,
        on_wishlist: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=None)
        lines = [f"## {title}", ""]
        if intro.strip():
            lines.append(intro.strip())
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("warframe_hub")])
        self.add_item(make_container(lines, accent=ACCENT_WARFRAME))

        row1 = ui.ActionRow()
        if on_refresh:
            refresh = ui.Button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄")
            refresh.callback = lambda i: on_refresh(i)  # type: ignore[assignment]
            row1.add_item(refresh)
        row1.add_item(_HintButton("Notify setup", "🔔", "`/wfnotify configure`", "recommended alert wizard"))
        row1.add_item(_HintButton("Post LFG", "🤝", "`/lfg`", "squad finder"))
        self.add_item(row1)

        row2 = ui.ActionRow()
        row2.add_item(_HintButton("Full status", "📋", "`/warframe status`", "full world-state board"))
        row2.add_item(_HintButton("My fissures", "💎", "`/warframe fissures`", "void fissure missions"))
        if on_wishlist and guild_id:
            wish = ui.Button(label="Baro wishlist", style=discord.ButtonStyle.secondary, emoji="⭐")
            wish.callback = lambda i: on_wishlist(i)  # type: ignore[assignment]
            row2.add_item(wish)
        self.add_item(row2)

        link_row = ui.ActionRow()
        link_row.add_item(
            ui.Button(
                label="Warframe Market",
                style=discord.ButtonStyle.link,
                url="https://warframe.market/",
                emoji="🛒",
            )
        )
        if BOT_WEBSITE:
            host = website_host() or "Website"
            link_row.add_item(
                ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE, emoji="🌐")
            )
        self.add_item(link_row)


class _HintButton(ui.Button):
    def __init__(self, label: str, emoji: str, command: str, detail: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, emoji=emoji)
        self._command = command
        self._detail = detail

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Run {self._command} — {self._detail}.",
            ephemeral=True,
        )
