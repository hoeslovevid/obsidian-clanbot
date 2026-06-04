"""Discord Components V2 quick menu (LayoutView pilot)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE
from core.embed_assets import EMBED_BANNER_URL
from core.help_layout import help_layout_v2_enabled
from core.presence import website_host


def menu_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class MenuHomeLayout(ui.LayoutView):
    """V2 layout splash for /menu — use **Open picker** for the classic select menu."""

    def __init__(
        self,
        *,
        recent_blurb: str,
        on_open_picker: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self._on_open_picker = on_open_picker

        lines = ["## Quick Menu"]
        if recent_blurb:
            lines.extend(["", recent_blurb.strip()])
        lines.extend(
            [
                "",
                "**Quick start** — daily, profile, baro, ticket, trade, and more.",
                "",
                "👤 **Me** — `/daily` · `/profile` · `/me` · `/preferences`",
                "🎮 **Warframe** — `/baro` · `/fissures` · `/lfg` · `/trade`",
                "👥 **Community** — `/ticket` · `/case` · `/poll`",
                "🔍 **Find anything** — `/search` · `/help`",
            ]
        )

        container = ui.Container(
            ui.TextDisplay(content="\n".join(line for line in lines if line is not None)),
            accent_color=discord.Color.from_str("#7C83FF"),
        )
        if EMBED_BANNER_URL:
            try:
                container.add_item(
                    ui.MediaGallery(discord.UnfurledMediaItem(url=EMBED_BANNER_URL))
                )
            except Exception:
                pass
        self.add_item(container)

        row = ui.ActionRow()
        row.add_item(OpenMenuPickerButton(on_open_picker))
        if BOT_WEBSITE:
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
        self.add_item(row)


class OpenMenuPickerButton(ui.Button):
    def __init__(self, on_open: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Open picker", style=discord.ButtonStyle.primary, emoji="⚡")
        self._on_open = on_open

    async def callback(self, interaction: discord.Interaction):
        await self._on_open(interaction)
