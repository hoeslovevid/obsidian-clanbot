"""Reusable link-button rows for embed messages."""
from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import quote

import discord  # type: ignore

from core.config import BOT_WEBSITE

WARFRAME_WIKI_URL = "https://wiki.warframe.com/"
WARFRAME_MARKET_URL = "https://warframe.market/"

# Website tool paths (relative to BOT_WEBSITE)
SITE_TOOL_PATHS = {
    "home": "/",
    "baro": "/baro.html",
    "nightwave": "/nightwave.html",
    "worth": "/worth.html",
    "rivens": "/rivens.html",
    "riven-grade": "/riven-grade.html",
    "relics": "/relics.html",
    "vault": "/vault.html",
    "planner": "/planner.html",
    "market": "/market.html",
    "farm": "/farm.html",
    "commands": "/commands.html",
    "circuit": "/circuit.html",
    "warframe": "/warframe.html",
}


def site_tool_url(tool: str, *, query: Optional[str] = None) -> Optional[str]:
    """Absolute URL for a website tool page, or None if BOT_WEBSITE is unset."""
    if not BOT_WEBSITE:
        return None
    base = BOT_WEBSITE.rstrip("/")
    path = SITE_TOOL_PATHS.get(tool) or (tool if tool.startswith("/") else f"/{tool}")
    url = f"{base}{path}"
    if query:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}q={quote(query)}"
    return url


def tool_link_button(
    label: str,
    tool: str,
    *,
    emoji: Optional[str] = None,
    query: Optional[str] = None,
) -> Optional[discord.ui.Button]:
    url = site_tool_url(tool, query=query)
    if not url:
        return None
    return link_button(label, url, emoji=emoji)


def link_button(label: str, url: str, *, emoji: Optional[str] = None) -> discord.ui.Button:
    kwargs: dict = {"label": label[:80], "style": discord.ButtonStyle.link, "url": url}
    if emoji:
        kwargs["emoji"] = emoji
    return discord.ui.Button(**kwargs)


def help_link_buttons() -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    cmds = tool_link_button("Commands", "commands", emoji="📜")
    if cmds:
        buttons.append(cmds)
    home = tool_link_button("Website", "home", emoji="🌐")
    if home:
        buttons.append(home)
    elif BOT_WEBSITE:
        buttons.append(link_button("Website", BOT_WEBSITE, emoji="🌐"))
    buttons.append(link_button("Warframe Wiki", WARFRAME_WIKI_URL, emoji="📖"))
    return buttons


def baro_link_buttons() -> list[discord.ui.Button]:
    buttons = [link_button("Warframe Market", WARFRAME_MARKET_URL, emoji="🛒")]
    baro = tool_link_button("Baro list", "baro", emoji="🌐")
    if baro:
        buttons.append(baro)
    elif BOT_WEBSITE:
        buttons.append(link_button("Obsidian", BOT_WEBSITE, emoji="🌐"))
    return buttons


def nightwave_link_buttons() -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    btn = tool_link_button("Nightwave checklist", "nightwave", emoji="🌙")
    if btn:
        buttons.append(btn)
    return buttons


def ticket_confirmation_buttons(*, channel_url: Optional[str] = None) -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    if channel_url:
        buttons.append(link_button("Open ticket", channel_url, emoji="🎫"))
    help_btn = tool_link_button("Help center", "commands", emoji="🌐")
    if help_btn:
        buttons.append(help_btn)
    elif BOT_WEBSITE:
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
