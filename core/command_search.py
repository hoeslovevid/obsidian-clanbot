"""Search registered slash commands by keyword (used by /general help_search)."""
from __future__ import annotations

import difflib
from typing import Iterable, Optional

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


def did_you_mean(bot, query: str, *, cutoff: float = 0.45) -> Optional[str]:
    """Fuzzy-match ``query`` against command paths (difflib fallback)."""
    q = (query or "").strip().lower()
    if len(q) < 2:
        return None
    paths = [p for p, _ in collect_command_entries(bot)]
    if not paths:
        return None
    # Match on full path and leaf segment
    candidates: list[str] = []
    for path in paths:
        candidates.append(path.lower())
        leaf = path.split()[-1].lower()
        if leaf not in candidates:
            candidates.append(leaf)
    close = difflib.get_close_matches(q, candidates, n=1, cutoff=cutoff)
    if not close:
        return None
    hit = close[0]
    for path in paths:
        if path.lower() == hit or path.split()[-1].lower() == hit:
            return path
    return None


def search_commands(
    bot,
    query: str,
    *,
    limit: int = 15,
    low_score_threshold: int = 25,
) -> tuple[list[tuple[str, str, int]], Optional[str]]:
    """Score and rank command paths matching ``query``.

    Returns ``(matches, did_you_mean_path)`` where ``did_you_mean_path`` is set when
    there are no matches or the best score is below ``low_score_threshold``.
    """
    SYNONYMS: dict[str, str] = {
        "coins": "economy balance daily coins wallet",
        "money": "economy balance daily wallet",
        "balance": "economy balance bal wallet",
        "wallet": "economy wallet balance xp streak",
        "streak": "economy daily wallet",
        "baro": "warframe baro void trader",
        "fissure": "warframe fissures void",
        "relic": "warframe fissures",
        "trade": "trading trade wts wtb platinum",
        "ticket": "community ticket support help",
        "report": "community request_help complaint case",
        "case": "community case_status complaint",
        "help": "general help menu search recent",
        "profile": "general profile me wallet",
        "poll": "general poll vote",
        "lfg": "lfg group mission",
        "pet": "pets shop feed",
        "warn": "warn warn moderation",
        "purge": "mod purge delete messages",
        "giveaway": "giveaways giveaway",
        "event": "events event_create",
        "dojo": "warframe dojo_research clan",
        "setup": "general setup_obsidian welcome",
        "recent": "general recent menu history",
    }

    q = (query or "").strip().lower()
    if not q:
        return [], None
    tokens = [t for t in q.split() if t]
    expanded = q
    for tok in tokens:
        if tok in SYNONYMS:
            expanded += " " + SYNONYMS[tok]
    search_tokens = [t for t in expanded.split() if t]
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
        elif all(tok in hay for tok in search_tokens):
            score += 35
        elif any(tok in hay for tok in search_tokens):
            score += 15
        else:
            # difflib-style partial: any token close to a path segment
            segments = path_l.replace("_", " ").split()
            for tok in tokens:
                if difflib.get_close_matches(tok, segments + [path_l], n=1, cutoff=0.72):
                    score += 12
            if score == 0:
                continue
        results.append((path, desc, score))
    results.sort(key=lambda x: (-x[2], len(x[0]), x[0]))
    trimmed = results[: max(1, int(limit))]

    suggestion: Optional[str] = None
    if not trimmed or trimmed[0][2] < low_score_threshold:
        suggestion = did_you_mean(bot, q)
        if suggestion and trimmed and any(suggestion == p for p, _, _ in trimmed):
            suggestion = None

    return trimmed, suggestion
