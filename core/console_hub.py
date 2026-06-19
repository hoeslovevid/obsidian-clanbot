"""Shared Clan Console hub button hints (classic + V2 layouts, restart-safe routing)."""
from __future__ import annotations

import logging

import discord  # type: ignore

logger = logging.getLogger(__name__)

# action suffix from custom_id ``obsidian_console:{action}``
CONSOLE_HUB_HINTS: dict[str, tuple[str, str]] = {
    "menu": ("/menu", "categorized command picker."),
    "daily": ("/daily", "claim your daily coin streak."),
    "wf_hub": ("/warframe hub", "Baro, fissures, notify setup."),
    "status": ("/status", "bot version, latency, and API health."),
    "ticket": ("/ticket", "open a support ticket."),
    "help": ("/help", "searchable command reference."),
}


async def respond_console_hub_hint(interaction: discord.Interaction, action: str) -> bool:
    """Reply with an ephemeral slash-command hint. Returns False if action is unknown."""
    hint = CONSOLE_HUB_HINTS.get(action)
    if not hint:
        return False
    if interaction.response.is_done():
        return True
    command, detail = hint
    try:
        await interaction.response.send_message(
            f"Run **`{command}`** — {detail}",
            ephemeral=True,
        )
    except (discord.InteractionResponded, discord.HTTPException) as exc:
        code = getattr(exc, "code", None)
        if isinstance(exc, discord.InteractionResponded) or code == 40060:
            logger.debug("[console_hub] duplicate acknowledge for action=%s", action)
            return True
        raise
    return True
