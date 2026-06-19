"""Components V2 admin console hub layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, footer_display, make_container

_LAYOUT_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("Menu", "📋", "menu"),
    ("Daily", "🎁", "daily"),
    ("WF Hub", "🎮", "wf_hub"),
    ("Status", "✅", "status"),
    ("Ticket", "🎫", "ticket"),
    ("Help", "❓", "help"),
)


class ConsoleHubLayout(ui.LayoutView):
    """Pinned clan console — hint buttons on ActionRows (handler-routed, no callbacks)."""

    def __init__(self, *, body: str):
        super().__init__(timeout=None)
        lines = ["## 🜂 Obsidian Clan Console", "", body.strip(), "", footer_display("console_hub")]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        row1 = ui.ActionRow()
        for label, emoji, action in _LAYOUT_BUTTONS[:3]:
            row1.add_item(_console_hint_button(label, emoji, action))
        row2 = ui.ActionRow()
        for label, emoji, action in _LAYOUT_BUTTONS[3:]:
            row2.add_item(_console_hint_button(label, emoji, action))
        self.add_item(row1)
        self.add_item(row2)


def _console_hint_button(label: str, emoji: str, action: str) -> ui.Button:
    style = discord.ButtonStyle.primary if label in ("Menu", "WF Hub") else discord.ButtonStyle.secondary
    return ui.Button(
        label=label,
        style=style,
        emoji=emoji,
        custom_id=f"obsidian_console:{action}",
    )
