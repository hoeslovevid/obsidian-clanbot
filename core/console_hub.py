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
    # #region agent log
    from core.debug_agent_log import agent_log

    agent_log(
        "console_hub.py:respond",
        "console hint requested",
        data={"action": action, "response_is_done": interaction.response.is_done()},
        hypothesis_id="H1-H3",
    )
    # #endregion
    hint = CONSOLE_HUB_HINTS.get(action)
    if not hint:
        return False
    command, detail = hint
    try:
        await interaction.response.send_message(
            f"Run **`{command}`** — {detail}",
            ephemeral=True,
        )
        # #region agent log
        agent_log(
            "console_hub.py:respond",
            "hint sent",
            data={"action": action},
            hypothesis_id="H3",
        )
        # #endregion
    except Exception as exc:
        # #region agent log
        agent_log(
            "console_hub.py:respond",
            "hint send failed",
            data={"action": action, "error": type(exc).__name__, "msg": str(exc)[:200]},
            hypothesis_id="H3",
        )
        # #endregion
        raise
    return True
