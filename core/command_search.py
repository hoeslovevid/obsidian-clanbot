"""Search registered slash commands by keyword (used by /search and /help)."""
from __future__ import annotations

import difflib
from typing import Iterable, Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

# Groups hidden from help/search for non-moderators.
MOD_ONLY_GROUPS: frozenset[str] = frozenset(
    {"mod", "automod", "warn", "roletools", "admin", "updates"}
)

# Longest-prefix wins. Maps command path prefixes to per-guild toggle keys in TOGGLEABLE_FEATURES.
COMMAND_FEATURE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("wfnotify",), "notifications"),
    (("warframe", "subscribe"), "notifications"),
    (("warframe", "notify"), "notifications"),
    (("economy", "gambling"), "gambling"),
    (("gambling",), "gambling"),
    (("pets",), "pets"),
    (("lfg",), "lfg"),
    (("trading",), "trade"),
    (("trade",), "trade"),
    (("events",), "events"),
    (("general", "poll"), "polls"),
    (("poll",), "polls"),
]

_ECONOMY_PATH_ROOTS: frozenset[str] = frozenset(
    {
        "economy",
        "store",
        "daily",
        "wallet",
        "leaderboard",
        "bal",
        "bounties",
        "transfer",
        "prestige",
        "stash",
        "invest",
        "gamble",
    }
)


def feature_for_path(path: str) -> Optional[str]:
    """Return a TOGGLEABLE_FEATURES key when this path should respect guild toggles."""
    parts = tuple((path or "").strip().lower().split())
    if not parts:
        return None
    best: Optional[tuple[tuple[str, ...], str]] = None
    for prefix, feature in COMMAND_FEATURE_RULES:
        if len(parts) >= len(prefix) and parts[: len(prefix)] == prefix:
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, feature)
    if best:
        return best[1]
    if parts[0] == "pets":
        return "pets"
    if parts[0] in ("lfg",):
        return "lfg"
    if parts[0] in ("trading", "trade"):
        return "trade"
    if parts[0] in ("events", "event_create", "events_list"):
        return "events"
    if parts[0] == "wfnotify" or (len(parts) > 1 and parts[1] in ("notify", "subscribe")):
        return "notifications"
    return None


def path_is_economy(path: str) -> bool:
    """True when path is economy-related (respects global ECONOMY_ENABLED)."""
    parts = (path or "").strip().lower().split()
    return bool(parts) and parts[0] in _ECONOMY_PATH_ROOTS


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

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for path, desc in entries:
        if path in seen:
            continue
        seen.add(path)
        out.append((path, desc))
    return out


async def filter_entries_for_guild(
    guild_id: Optional[int],
    entries: list[tuple[str, str]],
    *,
    is_mod: bool = False,
) -> list[tuple[str, str]]:
    """Drop mod-only and guild-disabled commands from discovery lists."""
    from core.utils import ECONOMY_ENABLED, feature_enabled

    out: list[tuple[str, str]] = []
    for path, desc in entries:
        root = path.split()[0] if path else ""
        if not is_mod and root in MOD_ONLY_GROUPS:
            continue
        if not ECONOMY_ENABLED and path_is_economy(path):
            continue
        feat = feature_for_path(path)
        if feat and guild_id:
            if not await feature_enabled(int(guild_id), feat):
                continue
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
    entries: Optional[list[tuple[str, str]]] = None,
) -> tuple[list[tuple[str, str, int]], Optional[str]]:
    """Score and rank command paths matching ``query``.

    Pass ``entries`` when results are pre-filtered (guild feature toggles).
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
        "notify": "wfnotify configure panel baro cycles alerts",
        "dojo": "warframe dojo_research clan",
        "setup": "general setup_obsidian welcome",
        "recent": "general recent menu history",
        "favorite": "favorite_add favorites",
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
    source = entries if entries is not None else collect_command_entries(bot)
    for path, desc in source:
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
