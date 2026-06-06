"""Components V2 wallet layout (HELP_LAYOUT_V2 gate)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.embed_footers import footer_for
from core.help_layout import help_layout_v2_enabled
from core.layout_v2 import ACCENT_ECONOMY, compact_fields, make_container


def wallet_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class WalletLayout(ui.LayoutView):
    """V2 wallet — coins, XP, streak with Refresh on ActionRow."""

    def __init__(
        self,
        *,
        title: str,
        intro: str,
        fields: list[tuple[str, str, bool]],
        on_refresh: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", intro.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", f"-# {footer_for('economy_wallet')}"])
        self.add_item(make_container(lines, accent=ACCENT_ECONOMY))
        if on_refresh:
            row = ui.ActionRow()
            row.add_item(WalletRefreshButton(on_refresh))
            self.add_item(row)


class WalletRefreshButton(ui.Button):
    def __init__(self, on_refresh: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
        self._on_refresh = on_refresh

    async def callback(self, interaction: discord.Interaction):
        await self._on_refresh(interaction)


class WalletSnapshotLayout(WalletLayout):
    """Compact wallet summary."""

    def __init__(self, *, title: str, body: str, on_refresh=None):
        super().__init__(
            title=title,
            intro=body,
            fields=[],
            on_refresh=on_refresh,
        )
