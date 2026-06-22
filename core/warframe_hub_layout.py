"""Components V2 Warframe hub layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE
from core.layout_v2 import ACCENT_WARFRAME, compact_fields, footer_display, make_container
from core.presence import website_host
from core.refresh_panels import REFRESH_CUSTOM_ID


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
        refresh = ui.Button(
            label="Refresh",
            style=discord.ButtonStyle.primary,
            emoji="🔄",
            custom_id=REFRESH_CUSTOM_ID,
        )
        row1.add_item(refresh)
        row1.add_item(_hub_hint_button("Notify setup", "🔔", "wf_hub:notify_hint"))
        row1.add_item(_hub_hint_button("Post LFG", "🤝", "wf_hub:lfg_hint"))
        self.add_item(row1)

        row2 = ui.ActionRow()
        row2.add_item(_hub_hint_button("Full status", "📋", "wf_hub:status_hint"))
        row2.add_item(_hub_hint_button("My fissures", "💎", "wf_hub:my_fissures"))
        if on_wishlist and guild_id:
            row2.add_item(
                ui.Button(
                    label="Baro wishlist",
                    style=discord.ButtonStyle.secondary,
                    emoji="⭐",
                    custom_id="wf_hub:baro_wish",
                )
            )
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


def _hub_hint_button(label: str, emoji: str, custom_id: str) -> ui.Button:
    return ui.Button(
        label=label,
        style=discord.ButtonStyle.secondary,
        emoji=emoji,
        custom_id=custom_id,
    )
