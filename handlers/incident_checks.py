"""Global slash-command gates: incident mode + maintenance."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord  # type: ignore

from core.utils import is_mod
from database import get_guild_setting, now_utc, set_guild_setting

if TYPE_CHECKING:
    from bot.client import ClanBot

logger = logging.getLogger(__name__)


async def incident_mode_check(bot: "ClanBot", interaction: discord.Interaction) -> bool:
    from handlers.command_tracking import mark_command_start

    mark_command_start(interaction)
    try:
        if not interaction.guild:
            return True

        if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
            return True

        enabled = await get_guild_setting(interaction.guild.id, "incident_mode_enabled")
        if (enabled or "0") != "1":
            return True

        until_s = await get_guild_setting(interaction.guild.id, "incident_mode_until_ts")
        until_ts = int(until_s) if until_s and until_s.isdigit() else 0
        now_ts = int(now_utc().timestamp())
        if until_ts and now_ts > until_ts:
            await set_guild_setting(interaction.guild.id, "incident_mode_enabled", "0")
            await set_guild_setting(interaction.guild.id, "incident_mode_until_ts", "0")
            return True

        qualified = ""
        try:
            qualified = interaction.command.qualified_name if interaction.command else ""
        except Exception:
            qualified = ""

        allowed = {
            "mod",
            "mod logging",
            "mod incident",
            "mod kpis",
            "community ticket",
            "community ticket_close",
            "community event_create",
            "general help",
            "general bot_status",
            "status",
        }

        if qualified == "mod" or qualified.startswith("mod "):
            return True

        if qualified in allowed:
            return True

        msg = await get_guild_setting(interaction.guild.id, "incident_mode_message")
        reason = msg.strip() if msg else (
            "The server is in **incident mode** while staff handle an issue. "
            "Most commands are paused for now — you can still use **`/help`**, **`/status`**, or **`/ticket`**."
        )
        until_line = ""
        if until_ts and until_ts > now_ts:
            until_line = f"\n\n_Auto-resumes <t:{until_ts}:R> (<t:{until_ts}:F>)._"
        if not interaction.response.is_done():
            from core.embed_templates import embed_template

            await interaction.response.send_message(
                embed=embed_template(
                    "warning",
                    "🚨 Incident Mode",
                    f"{reason}{until_line}",
                    category="moderation",
                    client=bot,
                ),
                ephemeral=True,
            )
        return False
    except Exception:
        return True


def install_incident_mode_checks(bot: "ClanBot") -> None:
    """discord.py 2.6+: use CommandTree.interaction_check for global gates."""
    prev = getattr(bot.tree, "interaction_check", None)

    async def combined(interaction: discord.Interaction) -> bool:
        try:
            if prev:
                res = prev(interaction)
                if hasattr(res, "__await__"):
                    res = await res
                if res is False:
                    return False
        except Exception:
            pass

        try:
            from core.maintenance import maintenance_check

            if not await maintenance_check(interaction):
                return False
        except Exception:
            pass

        return await incident_mode_check(bot, interaction)

    try:
        bot.tree.interaction_check = combined  # type: ignore[attr-defined]
    except Exception:
        pass
