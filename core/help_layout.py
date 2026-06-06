"""Discord Components V2 help hub (LayoutView pilot)."""
from __future__ import annotations

from typing import Callable, Optional, Awaitable

import discord  # type: ignore
from discord import ui  # type: ignore

from core.config import BOT_WEBSITE, HELP_LAYOUT_V2
from core.embed_assets import EMBED_BANNER_URL
from core.presence import website_host


def help_layout_v2_enabled() -> bool:
    return HELP_LAYOUT_V2


class HelpHomeLayout(ui.LayoutView):
    """V2 layout splash for /help — use **Browse categories** for the classic picker."""

    def __init__(
        self,
        *,
        is_mod: bool,
        on_browse: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=300)
        self._on_browse = on_browse

        lines = [
            "## Command Reference",
            "**8 essentials** — start here:",
            "",
            "📋 **`/menu`** · 🔍 **`/search`** · ✅ **`/status`** · 📝 **`/whatsnew`**",
            "👤 **`/profile`** · 🎁 **`/daily`** · 🎮 **`/warframe hub`** · 🎫 **`/ticket`**",
            "",
            "Then **Browse categories** for everything else.",
        ]
        if is_mod:
            lines.append("**Staff tools:** `/admin dashboard` · `/mod purge` · `/automod status` · `/admin console`")
        lines.append("")
        lines.append("Type `/` and start typing to search. New? Try **`/menu`**.")

        container = ui.Container(
            ui.TextDisplay(content="\n".join(lines)),
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
        row.add_item(BrowseCategoriesButton(on_browse))
        if BOT_WEBSITE:
            host = website_host() or "Website"
            row.add_item(ui.Button(label=host[:80], style=discord.ButtonStyle.link, url=BOT_WEBSITE))
        self.add_item(row)


class BrowseCategoriesButton(ui.Button):
    def __init__(self, on_browse: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Browse categories", style=discord.ButtonStyle.primary, emoji="📋")
        self._on_browse = on_browse

    async def callback(self, interaction: discord.Interaction):
        await self._on_browse(interaction)
