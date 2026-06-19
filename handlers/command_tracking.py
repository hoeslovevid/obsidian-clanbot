"""Slash command usage tracking and slow-command logging."""
from __future__ import annotations

import logging
import time

import discord  # type: ignore

from database import now_utc

logger = logging.getLogger(__name__)

_cmd_start_times: dict[int, float] = {}


def mark_command_start(interaction: discord.Interaction) -> None:
    """Record interaction start time for slow-command diagnostics."""
    iid = getattr(interaction, "id", None)
    if iid is not None:
        _cmd_start_times[int(iid)] = time.perf_counter()


async def handle_app_command_completion(
    bot: discord.Client,
    interaction: discord.Interaction,
    command,
) -> None:
    """Record per-user slash command usage for /tools my_stats. Best-effort, never raises."""
    try:
        iid = getattr(interaction, "id", None)
        started = _cmd_start_times.pop(int(iid), None) if iid is not None else None
        if started is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms >= 3000:
                qn = (
                    command.qualified_name
                    if hasattr(command, "qualified_name")
                    else getattr(command, "name", "?")
                )
                logger.warning(
                    "[slow_cmd] /%s took %.0f ms (guild=%s user=%s)",
                    qn,
                    elapsed_ms,
                    getattr(interaction.guild, "id", None),
                    getattr(interaction.user, "id", None),
                )
    except Exception:
        pass
    try:
        if interaction.guild is None or interaction.user is None:
            return
        full_name = command.qualified_name if hasattr(command, "qualified_name") else getattr(command, "name", None)
        if not full_name:
            return
        from database import record_command_usage

        await record_command_usage(
            interaction.guild.id,
            interaction.user.id,
            str(full_name),
            now_utc().weekday(),
        )
        from core.command_hints import maybe_send_first_use_hint

        await maybe_send_first_use_hint(interaction, str(full_name))
    except Exception as err:
        logger.debug(f"[my_stats] failed to record usage: {err}")
