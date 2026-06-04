"""Introspect the in-memory app command tree (always use guild=None for global registration)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import discord
from discord import app_commands


@dataclass
class CommandTreeStats:
    top_level: int = 0
    groups: int = 0
    standalone: int = 0
    grouped_subcommands: int = 0
    oversized: list[str] = field(default_factory=list)
    top_level_names: list[str] = field(default_factory=list)
    group_summary: list[str] = field(default_factory=list)


def collect_command_tree_stats(bot: discord.Client) -> CommandTreeStats:
    """Walk bot.tree global commands (guild=None). Guild-scoped get_commands() is empty for this bot."""
    stats = CommandTreeStats()
    commands = bot.tree.get_commands(guild=None)

    for cmd in commands:
        stats.top_level += 1
        stats.top_level_names.append(cmd.name)
        if isinstance(cmd, app_commands.Group):
            stats.groups += 1
            sub_count = _count_group_subcommands(cmd)
            stats.grouped_subcommands += sub_count
            stats.group_summary.append(f"`/{cmd.name}` ({sub_count})")
            if len(cmd.commands) > 25:
                stats.oversized.append(f"`/{cmd.name}` ({len(cmd.commands)} direct subcommands)")
            for sub in cmd.commands:
                if isinstance(sub, app_commands.Group) and len(sub.commands) > 25:
                    stats.oversized.append(
                        f"`/{cmd.name} {sub.name}` ({len(sub.commands)} subcommands)"
                    )
        else:
            stats.standalone += 1

    stats.top_level_names.sort(key=str.lower)
    stats.group_summary.sort(key=str.lower)
    return stats


def _count_group_subcommands(group: app_commands.Group) -> int:
    """Count subcommands including one nested subgroup level (e.g. /mod channel)."""
    total = 0
    for sub in group.commands:
        total += 1
        if isinstance(sub, app_commands.Group):
            total += len(sub.commands)
    return total


def format_command_tree_field(stats: CommandTreeStats, *, sync_guild_id: Optional[int] = None) -> str:
    """Discord embed field body for command sync summary."""
    scope = f"guild `{sync_guild_id}`" if sync_guild_id else "global"
    lines = [
        f"**{stats.top_level}** top-level · **{stats.grouped_subcommands}** grouped subcommands",
        f"({stats.groups} groups, {stats.standalone} standalone shortcuts/commands)",
        f"Registered tree: {scope}",
    ]
    if stats.group_summary:
        preview = ", ".join(stats.group_summary[:12])
        if len(stats.group_summary) > 12:
            preview += f", … +{len(stats.group_summary) - 12} more"
        lines.append(f"Groups: {preview}")
    return "\n".join(lines)
