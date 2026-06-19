"""Resolve commands on the local app command tree (global registration first)."""
from __future__ import annotations

from typing import Iterable, Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore


def tree_root_commands(bot: discord.Client, guild: Optional[discord.Guild] = None) -> list:
    """Top-level tree commands — global registrations first, then guild-only."""
    roots = list(bot.tree.get_commands(guild=None))
    if guild:
        seen = {c.name for c in roots}
        for cmd in bot.tree.get_commands(guild=guild):
            if cmd.name not in seen:
                roots.append(cmd)
                seen.add(cmd.name)
    return roots


def find_tree_group(
    bot: discord.Client,
    name: str,
    guild: Optional[discord.Guild] = None,
) -> Optional[app_commands.Group]:
    for cmd in tree_root_commands(bot, guild):
        if isinstance(cmd, app_commands.Group) and cmd.name == name:
            return cmd
    return None


def find_tree_command(
    bot: discord.Client,
    path: Iterable[str],
    *,
    guild: Optional[discord.Guild] = None,
) -> app_commands.Command | app_commands.Group | None:
    """Resolve a command path like ['warframe', 'baro'] on the app command tree."""
    parts = list(path)
    if not parts:
        return None
    current = None
    for i, name in enumerate(parts):
        if i == 0:
            current = next((c for c in tree_root_commands(bot, guild) if c.name == name), None)
        elif current and isinstance(current, app_commands.Group):
            current = next((c for c in current.commands if c.name == name), None)
        else:
            return None
        if current is None:
            return None
    return current
