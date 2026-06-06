"""Components V2 onboarding layout."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, footer_display, make_container


class OnboardingLayout(ui.LayoutView):
    """3-step onboarding with ActionRow buttons."""

    def __init__(
        self,
        *,
        guild_name: str,
        display_name: str,
        on_timezone: Callable[[discord.Interaction], Awaitable[None]],
        on_platform: Callable[[discord.Interaction], Awaitable[None]],
        on_menu: Callable[[discord.Interaction], Awaitable[None]],
        on_done: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=300)
        lines = [
            f"## 👋 Welcome to {guild_name}!",
            "",
            f"Hi **{display_name}** — tap a step to get started:",
            "",
            "**1.** Timezone · **2.** Platform (`/preferences`) · **3.** `/menu` quick picks",
            "",
            footer_display("onboarding"),
        ]
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))
        row = ui.ActionRow()
        for label, emoji, cb in (
            ("1 · Timezone", "🌐", on_timezone),
            ("2 · Platform", "🎮", on_platform),
            ("3 · Menu", "📋", on_menu),
        ):
            btn = ui.Button(label=label, style=discord.ButtonStyle.primary, emoji=emoji)
            btn.callback = lambda i, fn=cb: fn(i)  # type: ignore[assignment]
            row.add_item(btn)
        self.add_item(row)
        if on_done:
            done_row = ui.ActionRow()
            done = ui.Button(label="Done", style=discord.ButtonStyle.secondary, emoji="✅")
            done.callback = lambda i: on_done(i)  # type: ignore[assignment]
            done_row.add_item(done)
            self.add_item(done_row)
