"""Reusable link buttons and views for embeds."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore

from core.utils import channel_jump_url, message_jump_url


def link_button(label: str, url: str, *, emoji: Optional[str] = None) -> discord.ui.Button:
    """Discord link-style button."""
    return discord.ui.Button(
        label=label[:80],
        url=url,
        style=discord.ButtonStyle.link,
        emoji=emoji,
    )


def channel_link_button(label: str, guild_id: int, channel_id: int) -> discord.ui.Button:
    return link_button(label, channel_jump_url(guild_id, channel_id))


def thread_link_button(label: str, guild_id: int, channel_id: int, message_id: int) -> discord.ui.Button:
    return link_button(label, message_jump_url(guild_id, channel_id, message_id))


class LinkRowView(discord.ui.View):
    """Ephemeral-friendly view with up to 5 link buttons."""

    def __init__(self, *buttons: discord.ui.Button, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        for btn in buttons[:5]:
            self.add_item(btn)
