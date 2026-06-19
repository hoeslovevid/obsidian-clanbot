"""Components V2 admin console hub layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, footer_display, make_container


class ConsoleHubLayout(ui.LayoutView):
    """Pinned clan console — hint buttons on ActionRows."""

    def __init__(self, *, body: str):
        super().__init__(timeout=None)
        lines = ["## 🜂 Obsidian Clan Console", "", body.strip(), "", footer_display("console_hub")]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        row1 = ui.ActionRow()
        for label, emoji, cmd, hint in (
            ("Menu", "📋", "/menu", "categorized command picker"),
            ("Daily", "🎁", "/daily", "claim your daily coin streak"),
            ("WF Hub", "🎮", "/warframe hub", "Baro, fissures, notify setup"),
        ):
            row1.add_item(_ConsoleHintButton(label, emoji, cmd, hint))
        row2 = ui.ActionRow()
        for label, emoji, cmd, hint in (
            ("Status", "✅", "/status", "bot version and API health"),
            ("Ticket", "🎫", "/ticket", "open a support ticket"),
            ("Help", "❓", "/help", "searchable command reference"),
        ):
            row2.add_item(_ConsoleHintButton(label, emoji, cmd, hint))
        self.add_item(row1)
        self.add_item(row2)


class _ConsoleHintButton(ui.Button):
    def __init__(self, label: str, emoji: str, command: str, detail: str):
        style = discord.ButtonStyle.primary if label in ("Menu", "WF Hub") else discord.ButtonStyle.secondary
        super().__init__(label=label, style=style, emoji=emoji, custom_id=f"obsidian_console:{label.lower().replace(' ', '_')}")
        self._command = command
        self._detail = detail

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Run **`{self._command}`** — {self._detail}",
            ephemeral=True,
        )
