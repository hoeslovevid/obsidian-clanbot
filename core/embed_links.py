"""Reusable link-button rows for embed messages."""
from __future__ import annotations

from typing import Iterable, Optional

import discord  # type: ignore

from core.config import BOT_WEBSITE

WARFRAME_WIKI_URL = "https://wiki.warframe.com/"
WARFRAME_MARKET_URL = "https://warframe.market/"


def link_button(label: str, url: str, *, emoji: Optional[str] = None) -> discord.ui.Button:
    kwargs: dict = {"label": label[:80], "style": discord.ButtonStyle.link, "url": url}
    if emoji:
        kwargs["emoji"] = emoji
    return discord.ui.Button(**kwargs)


def help_link_buttons() -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    if BOT_WEBSITE:
        buttons.append(link_button("Website", BOT_WEBSITE, emoji="🌐"))
    buttons.append(link_button("Warframe Wiki", WARFRAME_WIKI_URL, emoji="📖"))
    return buttons


def baro_link_buttons() -> list[discord.ui.Button]:
    buttons = [link_button("Warframe Market", WARFRAME_MARKET_URL, emoji="🛒")]
    if BOT_WEBSITE:
        buttons.append(link_button("Obsidian", BOT_WEBSITE, emoji="🌐"))
    return buttons


def ticket_confirmation_buttons(*, channel_url: Optional[str] = None) -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    if channel_url:
        buttons.append(link_button("Open ticket", channel_url, emoji="🎫"))
    if BOT_WEBSITE:
        buttons.append(link_button("Help center", BOT_WEBSITE, emoji="🌐"))
    return buttons


def channel_link_button(label: str, guild_id: int, channel_id: int) -> discord.ui.Button:
    """Link button that opens a guild text/voice channel in the Discord client."""
    url = f"https://discord.com/channels/{guild_id}/{channel_id}"
    return link_button(label, url)


class LinkRowView(discord.ui.View):
    """View with a single row of link buttons (max 5)."""

    def __init__(self, *buttons: discord.ui.Button):
        super().__init__(timeout=None)
        add_link_row(self, buttons)


def add_link_row(
    view: discord.ui.View | discord.ui.LayoutView,
    buttons: Iterable[discord.ui.Button],
) -> None:
    """Append link buttons (max 5). Classic View: one item per button; LayoutView: one ActionRow."""
    items = list(buttons)[:5]
    if not items:
        return
    if isinstance(view, discord.ui.LayoutView):
        row = discord.ui.ActionRow()
        for btn in items:
            row.add_item(btn)
        view.add_item(row)
        return
    for btn in items:
        view.add_item(btn)
