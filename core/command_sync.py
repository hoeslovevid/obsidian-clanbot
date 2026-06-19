"""Slash command sync for multi-guild deployments."""
from __future__ import annotations

import logging
from typing import Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.command_tree_stats import CommandTreeStats, collect_command_tree_stats, format_command_tree_field
from core.config import COMMAND_SYNC_GUILD_ONLY, GUILD_ID

logger = logging.getLogger(__name__)


def sync_scope_description(guild_id: Optional[int] = None) -> str:
    if guild_id:
        return f"guild `{guild_id}` (dev fast-sync)"
    return "global (all guilds)"


def should_use_guild_sync() -> bool:
    """Guild-only sync is opt-in for local dev; production multi-guild uses global."""
    return bool(GUILD_ID and COMMAND_SYNC_GUILD_ONLY)


async def sync_app_commands(bot: discord.Client) -> tuple[Optional[int], CommandTreeStats]:
    """Sync the command tree. Returns (sync_guild_id or None, CommandTreeStats)."""
    stats = collect_command_tree_stats(bot)
    guild_id: Optional[int] = None

    if should_use_guild_sync():
        guild_id = GUILD_ID
        await bot.tree.sync(guild=discord.Object(id=guild_id))
        logger.info("[sync] Synced to guild %s (COMMAND_SYNC_GUILD_ONLY)", guild_id)
    else:
        await bot.tree.sync()
        logger.info("[sync] Synced globally (%s guilds on shard)", len(bot.guilds))

    _log_tree_summary(bot, stats, guild_id)
    return guild_id, stats


def _log_tree_summary(bot: discord.Client, stats: CommandTreeStats, guild_id: Optional[int]) -> None:
    commands_list = [cmd.name for cmd in bot.tree.get_commands(guild=None)]
    scope = sync_scope_description(guild_id)
    print(f"[sync] Synced {len(commands_list)} top-level commands/groups ({scope})")
    print(f"[sync] Top-level: {', '.join(commands_list)}")

    total_subcommands = 0
    for cmd in bot.tree.get_commands(guild=None):
        if isinstance(cmd, app_commands.Group):
            subcommands = [subcmd.name for subcmd in cmd.commands]
            total_subcommands += len(subcommands)
            if subcommands:
                preview = ", ".join(sorted(subcommands[:10]))
                suffix = "..." if len(subcommands) > 10 else ""
                print(f"[sync] Group '{cmd.name}' has {len(subcommands)} subcommands: {preview}{suffix}")
            else:
                print(f"[sync] WARNING: Group '{cmd.name}' has NO subcommands!")
    print(f"[sync] Total subcommands synced: {total_subcommands}")

    if stats.headroom_warnings:
        print(f"[sync] HEADROOM: {', '.join(stats.headroom_warnings)}")
    if stats.oversized:
        print(f"[sync] OVERSIZED: {', '.join(stats.oversized)}")


def format_sync_success_embed_body(stats: CommandTreeStats, *, guild_id: Optional[int] = None) -> str:
    return format_command_tree_field(stats, sync_guild_id=guild_id)
