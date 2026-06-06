"""Components V2 ticket member-facing layouts."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore
from discord import ui  # type: ignore

from core.layout_v2 import ACCENT_COMMUNITY, compact_fields, footer_display, make_container


class TicketOpenLayout(ui.LayoutView):
    """Confirmation after opening a ticket."""

    def __init__(
        self,
        *,
        ticket_id: str,
        channel_mention: str,
        fields: list[tuple[str, str, bool]],
        jump_url: Optional[str] = None,
    ):
        super().__init__(timeout=120)
        lines = [
            "## ✅ Ticket Created",
            "",
            f"Your ticket: {channel_mention}",
            f"**Ticket ID:** `{ticket_id}`",
        ]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("community_ticket_open")])
        self.add_item(make_container(lines, accent=ACCENT_COMMUNITY))
        if jump_url:
            row = ui.ActionRow()
            row.add_item(ui.Button(label="Open ticket", style=discord.ButtonStyle.link, url=jump_url))
            self.add_item(row)


class TicketStatusLayout(ui.LayoutView):
    """Member ticket status summary."""

    def __init__(self, *, title: str, body: str, fields: list[tuple[str, str, bool]]):
        super().__init__(timeout=120)
        lines = [f"## {title}", "", body.strip()]
        if fields:
            lines.extend(["", compact_fields(fields)])
        lines.extend(["", footer_display("community_ticket")])
        self.add_item(make_container(lines, accent=ACCENT_COMMUNITY))
