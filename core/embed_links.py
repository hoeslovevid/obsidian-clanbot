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


def add_link_row(view: discord.ui.View, buttons: Iterable[discord.ui.Button]) -> None:
    """Append a single ActionRow of link buttons (max 5)."""
    items = list(buttons)[:5]
    if not items:
        return
    row = discord.ui.ActionRow()
    for btn in items:
        row.add_item(btn)
    view.add_item(row)
