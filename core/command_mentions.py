"""Clickable slash-command mentions (``</name:id>``).

Discord renders ``</warframe baro:123456789>`` as a clickable command chip.
We can only build these once the application commands are registered (the IDs
are assigned by Discord), so the registry is refreshed on startup from
``tree.fetch_commands()``.

Usage:
    from core.command_mentions import command_mention, linkify_command_mentions

    command_mention("warframe baro")          -> "</warframe baro:123>" or "`/warframe baro`"
    linkify_command_mentions("Use `/help`")   -> upgrades known commands in text
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import discord  # type: ignore

logger = logging.getLogger(__name__)

# qualified path (lowercase, space-separated) -> "</path:id>"
_MENTIONS: dict[str, str] = {}

# Matches a backtick-wrapped slash command, e.g. `/help` or `/warframe baro`.
_BACKTICK_CMD_RE = re.compile(r"`/([a-zA-Z0-9][a-zA-Z0-9 _-]*?)`")


async def refresh_command_mentions(bot: discord.Client) -> None:
    """Populate the registry from the live command tree. Safe to call repeatedly."""
    from core.config import GUILD_ID

    try:
        guild = discord.Object(id=GUILD_ID) if GUILD_ID else None
        cmds = await bot.tree.fetch_commands(guild=guild)
    except Exception as exc:
        logger.warning(f"[command_mentions] fetch_commands failed: {exc}")
        return

    out: dict[str, str] = {}
    for cmd in cmds:
        base = cmd.name
        out[base.lower()] = f"</{base}:{cmd.id}>"
        for opt in getattr(cmd, "options", None) or []:
            # AppCommandGroup represents both subcommands and subcommand groups;
            # plain parameters are Argument and are skipped.
            if isinstance(opt, discord.app_commands.AppCommandGroup):
                sub = f"{base} {opt.name}"
                out[sub.lower()] = f"</{sub}:{cmd.id}>"
                for opt2 in getattr(opt, "options", None) or []:
                    if isinstance(opt2, discord.app_commands.AppCommandGroup):
                        sub2 = f"{sub} {opt2.name}"
                        out[sub2.lower()] = f"</{sub2}:{cmd.id}>"

    _MENTIONS.clear()
    _MENTIONS.update(out)
    logger.info(f"[command_mentions] registered {len(_MENTIONS)} clickable command paths")


def command_mention(path: str, *, fallback: Optional[str] = None) -> str:
    """Return ``</path:id>`` for a qualified command path, or a ``/path`` fallback."""
    key = (path or "").strip().lstrip("/").lower()
    mention = _MENTIONS.get(key)
    if mention:
        return mention
    return fallback if fallback is not None else f"`/{key}`"


def linkify_command_mentions(text: str) -> str:
    """Upgrade backtick-wrapped slash commands in ``text`` to clickable mentions.

    Only commands present in the registry are upgraded; everything else is left
    untouched, so unknown or stale references degrade gracefully to plain text.
    """
    if not text or not _MENTIONS:
        return text

    def _repl(match: "re.Match[str]") -> str:
        key = match.group(1).strip().lower()
        return _MENTIONS.get(key, match.group(0))

    return _BACKTICK_CMD_RE.sub(_repl, text)
