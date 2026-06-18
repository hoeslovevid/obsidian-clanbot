"""Global maintenance mode — blocks member commands with a branded message."""
from __future__ import annotations

import os

import discord

from core.config import BOT_VERSION
from core.utils import obsidian_embed

_MAINTENANCE = os.getenv("MAINTENANCE_MODE", "false").lower() in ("1", "true", "yes", "on")
_MAINTENANCE_MSG = (
    os.getenv("MAINTENANCE_MESSAGE", "").strip()
    or "Obsidian Bot is undergoing scheduled maintenance. Please try again shortly."
)


def maintenance_enabled() -> bool:
    return _MAINTENANCE


def maintenance_message() -> str:
    return _MAINTENANCE_MSG


async def maintenance_check(interaction: discord.Interaction) -> bool:
    """Return True if the command may proceed. Mods always bypass."""
    if not _MAINTENANCE:
        return True
    if not interaction.guild:
        return True
    from core.utils import is_mod

    if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
        return True
    qualified = ""
    try:
        qualified = interaction.command.qualified_name if interaction.command else ""
    except Exception:
        pass
    if qualified in {"status", "about", "whatsnew", "help", "admin health"}:
        return True
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=_maintenance_embed(interaction.client), ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=_maintenance_embed(interaction.client),
                ephemeral=True,
            )
    except Exception:
        pass
    return False


def _maintenance_embed(client) -> discord.Embed:
    return obsidian_embed(
        "🔧 Maintenance",
        maintenance_message(),
        color=discord.Color.orange(),
        footer=f"v{BOT_VERSION} · /status for bot health",
        client=client,
    )
