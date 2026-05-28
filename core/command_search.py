"""Search registered slash commands by keyword (used by /general help_search)."""
from __future__ import annotations

from typing import Iterable

import discord  # type: ignore
from discord import app_commands  # type: ignore


def collect_command_entries(bot) -> list[tuple[str, str]]:
    """Return ``(path, description)`` for every slash command on the tree."""
    entries: list[tuple[str, str]] = []

    def _walk(group_or_cmds: Iterable, prefix: list[str]) -> None:
        for cmd in group_or_cmds:
            current = prefix + [cmd.name]
            if isinstance(cmd, app_commands.Group):
                _walk(cmd.commands, current)
            elif isinstance(cmd, app_commands.Command):
                path = " ".join(current)
                desc = (cmd.description or "").strip()
                entries.append((path, desc))

    try:
        for top in bot.tree.get_commands(guild=None):
            if isinstance(top, app_commands.ContextMenu):
                continue
            if isinstance(top, app_commands.Group):
                _walk(top.commands, [top.name])
            elif isinstance(top, app_commands.Command):
                entries.append((top.name, (top.description or "").strip()))
    except Exception:
        pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for path, desc in entries:
        if path in seen:
            continue
        seen.add(path)
        out.append((path, desc))
    return out


def search_commands(bot, query: str, *, limit: int = 15) -> list[tuple[str, str, int]]:
    """Score and rank command paths matching ``query``.

    Returns ``(path, description, score)`` sorted best-first.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in q.split() if t]
    results: list[tuple[str, str, int]] = []
    for path, desc in collect_command_entries(bot):
        path_l = path.lower()
        desc_l = desc.lower()
        hay = f"{path_l} {desc_l}"
        score = 0
        if path_l == q:
            score += 100
        elif path_l.startswith(q):
            score += 80
        elif q in path_l:
            score += 60
        elif all(tok in hay for tok in tokens):
            score += 40 + sum(10 for tok in tokens if tok in path_l)
        elif any(tok in hay for tok in tokens):
            score += 20
        else:
            continue
        results.append((path, desc, score))
    results.sort(key=lambda x: (-x[2], len(x[0]), x[0]))
    return results[: max(1, int(limit))]
