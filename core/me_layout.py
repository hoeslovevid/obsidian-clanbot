"""Components V2 /me layout."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_DEFAULT, compact_fields, make_container


class MeLayout(ui.LayoutView):
    def __init__(
        self,
        *,
        title: str,
        intro: str,
        fields: list[tuple[str, str, bool]],
        footer: str,
        chips: str = "",
    ):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", intro.strip()]
        if chips:
            lines.extend(["", chips.strip()])
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", f"-# {footer}"])
        self.add_item(make_container(lines, accent=ACCENT_DEFAULT))

        row = ui.ActionRow()
        for label, emoji, cmd in (
            ("Daily", "🎁", "/daily"),
            ("Menu", "📋", "/menu"),
            ("Profile", "👤", "/profile"),
        ):
            btn = ui.Button(label=label, style=discord.ButtonStyle.secondary, emoji=emoji)

            def _make_hint(slash: str):
                async def _hint(inter: discord.Interaction):
                    await inter.response.send_message(
                        f"Run **`{slash}`** to continue.", ephemeral=True
                    )
                return _hint

            btn.callback = _make_hint(cmd)  # type: ignore[assignment]
            row.add_item(btn)
        self.add_item(row)
