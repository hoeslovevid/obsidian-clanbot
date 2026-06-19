"""Component/modal interaction router + auto-defer safety net."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import discord  # type: ignore

logger = logging.getLogger(__name__)

AUTO_DEFER_AFTER_SECONDS = float(os.getenv("AUTO_DEFER_AFTER_SECONDS", "2.5"))


async def auto_defer_watchdog(interaction: discord.Interaction) -> None:
    try:
        await asyncio.sleep(AUTO_DEFER_AFTER_SECONDS)
        if interaction.response.is_done():
            return
        await interaction.response.defer()
    except (discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as exc:
        logger.debug(f"[auto_defer] watchdog skipped: {exc}")


async def handle_interaction(bot: discord.Client, interaction: discord.Interaction) -> None:
    """Route modals/components; track slash usage; auto-defer slow commands."""
    if interaction.type == discord.InteractionType.application_command:
        asyncio.create_task(auto_defer_watchdog(interaction))
        if isinstance(interaction.user, discord.Member) and interaction.guild:
            idata_cmd: Any = interaction.data or {}
            command_name = idata_cmd.get("name", "")
            if command_name not in ["activity", "activity_leaderboard"]:
                try:
                    from database import track_command_usage

                    await track_command_usage(interaction.guild.id, interaction.user.id)
                except Exception as e:
                    logger.debug(f"Failed to track command usage: {e}")
                try:
                    from core.command_history import qualified_command_name, record_recent_command

                    path = qualified_command_name(interaction)
                    if path:
                        await record_recent_command(interaction.guild.id, interaction.user.id, path)
                except Exception as e:
                    logger.debug(f"Failed to record recent command: {e}")
        return

    if interaction.type == discord.InteractionType.modal_submit:
        from handlers.modal_handler import handle_modal_submit

        await handle_modal_submit(bot, interaction)
        return

    if interaction.type == discord.InteractionType.component:
        from handlers.component_handler import handle_component

        await handle_component(bot, interaction)
