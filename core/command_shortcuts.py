"""Register top-level slash shortcuts that mirror nested commands."""
from __future__ import annotations

import logging
from typing import Iterable

import discord  # type: ignore
from discord import app_commands  # type: ignore

logger = logging.getLogger(__name__)

# (source path, shortcut name, description)
SHORTCUTS: list[tuple[list[str], str, str]] = [
    (["general", "help"], "help", "Browse all bot commands — categories, search tips, examples"),
    (["general", "help_search"], "search", "Find a command by keyword — coins, baro, ticket, trade"),
    (["community", "ticket"], "ticket", "Open a support ticket — roles, bugs, questions, help"),
    (["trading", "trade"], "trade", "Post a WTS/WTB trade listing — platinum items, market prices"),
    (["warframe", "baro"], "baro", "Baro Ki'Teer — inventory, arrival time, void trader"),
    (["warframe", "fissures"], "fissures", "Void fissure missions — Lith, Meso, Neo, Axi, Requiem"),
    (["general", "poll"], "poll", "Create a server poll — members vote with reactions"),
]


from core.command_tree import find_tree_command as _find_tree_command


def find_tree_command(
    bot: discord.Client,
    path: Iterable[str],
    *,
    guild: discord.Guild | None = None,
) -> app_commands.Command | app_commands.Group | None:
    """Resolve a command path like ['warframe', 'baro'] on the app command tree."""
    return _find_tree_command(bot, path, guild=guild)


def register_command_shortcut(
    bot: discord.Client,
    source_path: list[str],
    shortcut_name: str,
    description: str,
) -> bool:
    """Register a top-level command that reuses an existing handler."""
    source = find_tree_command(bot, source_path)
    if not isinstance(source, app_commands.Command):
        logger.warning("[shortcuts] Source not found or not a command: %s", " ".join(source_path))
        return False
    shortcut = app_commands.Command(
        name=shortcut_name,
        description=description,
        callback=source.callback,
    )
    try:
        bot.tree.add_command(shortcut)
        logger.info("[shortcuts] Registered /%s -> /%s", shortcut_name, " ".join(source_path))
        return True
    except Exception as e:
        logger.debug("[shortcuts] Could not register /%s: %s", shortcut_name, e)
        return False


def register_all_shortcuts(bot: discord.Client) -> int:
    """Register all configured shortcuts. Returns count registered."""
    count = 0
    for path, name, desc in SHORTCUTS:
        if register_command_shortcut(bot, path, name, desc):
            count += 1
    return count
