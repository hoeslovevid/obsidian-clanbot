"""First-use slash command tips (one ephemeral hint per command)."""
from __future__ import annotations

from typing import Optional

import discord  # type: ignore

from database import get_guild_setting, set_guild_setting

# command qualified name -> short tip
COMMAND_HINTS: dict[str, str] = {
    "daily": "Claim free coins once per day. Streaks boost rewards — come back tomorrow!",
    "baro": "Shows Void Trader inventory and countdown. Tap **Update data** to refresh.",
    "fissures": "Live void fissures — filter by tier in the command options.",
    "menu": "Quick launcher for common actions. Your **Recent** commands appear at the top.",
    "help": "Browse categories or use **`/search`** to find any command by keyword.",
    "profile": "Your stats, bio, and achievements. Set a bio from the button on your profile.",
    "wallet": "Coins, XP, streak, and daily timer in one place — tap **Refresh**.",
    "recent": "Your last few slash commands with quick tips — rerun anything from the list.",
    "lfg": "Post a looking-for-group ad. Use **templates** for Steel Path / Sortie / Archon.",
    "trade": "WTS/WTB listings for the clan trading channel.",
    "ticket": "Opens a private staff thread — describe your issue in the subject.",
}


async def hint_already_seen(guild_id: int, user_id: int, command_name: str) -> bool:
    val = await get_guild_setting(guild_id, f"cmd_hint_seen:{user_id}:{command_name}")
    return val == "1"


async def mark_hint_seen(guild_id: int, user_id: int, command_name: str) -> None:
    await set_guild_setting(guild_id, f"cmd_hint_seen:{user_id}:{command_name}", "1")


async def maybe_send_first_use_hint(
    interaction: discord.Interaction,
    command_name: str,
) -> None:
    """Send a one-time ephemeral tip if configured and not yet seen."""
    if not interaction.guild or not interaction.user:
        return
    tip = COMMAND_HINTS.get(command_name) or COMMAND_HINTS.get(command_name.split()[-1])
    if not tip:
        return
    if await hint_already_seen(interaction.guild.id, interaction.user.id, command_name):
        return
    await mark_hint_seen(interaction.guild.id, interaction.user.id, command_name)
    try:
        from core.utils import obsidian_embed

        emb = obsidian_embed(
            "💡 Quick tip",
            tip,
            category="general",
            client=interaction.client,
        )
        await interaction.followup.send(embed=emb, ephemeral=True)
    except Exception:
        pass
