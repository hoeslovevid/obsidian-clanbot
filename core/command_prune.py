"""Command prune analysis — heatmap-driven low-traffic command reports."""
from __future__ import annotations

import discord  # type: ignore

from core.command_usage_report import (
    format_prune_hint,
    format_usage_field,
    guild_top_commands,
    never_used_commands,
)


async def guild_usage_summary(
    bot: discord.Client,
    guild_id: int,
    *,
    top_limit: int = 8,
    unused_limit: int = 12,
) -> tuple[list[tuple[str, int]], list[str]]:
    top = await guild_top_commands(guild_id, limit=top_limit)
    unused = await never_used_commands(bot, guild_id, limit=unused_limit)
    return top, unused


async def format_guild_usage_embed_body(
    bot: discord.Client,
    guild_id: int,
) -> str:
    top, unused = await guild_usage_summary(bot, guild_id)
    return format_usage_field(top, unused=unused)


def prune_candidate_count(unused: list[str], *, registered_total: int | None = None) -> str:
    n = len(unused)
    if registered_total is not None and n < registered_total:
        return f"{n}+ never used (showing sample)"
    return f"{n} never used"
