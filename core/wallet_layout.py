"""Components V2 wallet layout pilot (HELP_LAYOUT_V2 gate)."""
from __future__ import annotations

import discord  # type: ignore
from discord import ui  # type: ignore

from core.embed_assets import EMBED_BANNER_URL
from core.embed_footers import footer_for
from core.help_layout import help_layout_v2_enabled


def wallet_layout_v2_enabled() -> bool:
    return help_layout_v2_enabled()


class WalletSnapshotLayout(ui.LayoutView):
    """V2 wallet summary — pair with classic embed_template wallet card."""

    def __init__(self, *, title: str, body: str):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", body.strip(), "", f"-# {footer_for('economy_wallet')}"]
        container = ui.Container(
            ui.TextDisplay(content="\n".join(lines)),
            accent_color=discord.Color.from_str("#F0A800"),
        )
        if EMBED_BANNER_URL:
            try:
                container.add_item(
                    ui.MediaGallery(discord.UnfurledMediaItem(url=EMBED_BANNER_URL))
                )
            except Exception:
                pass
        self.add_item(container)
