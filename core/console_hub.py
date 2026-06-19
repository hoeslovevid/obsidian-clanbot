"""Shared Clan Console hub button hints (classic + V2 layouts, restart-safe routing)."""
from __future__ import annotations

import discord  # type: ignore

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
    command, detail = hint
    await interaction.response.send_message(
        f"Run **`{command}`** — {detail}",
        ephemeral=True,
    )
    return True
