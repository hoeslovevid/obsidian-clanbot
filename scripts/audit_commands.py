#!/usr/bin/env python3
"""Audit slash command tree: counts, headroom, merge candidates, Discovery 12."""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Avoid requiring a real token for local audit.
os.environ.setdefault("DISCORD_TOKEN", "audit-local-token-not-for-discord")

from discord import app_commands  # noqa: E402

from bot.client import create_bot  # noqa: E402
from core.command_search import (  # noqa: E402
    MOD_ONLY_GROUPS,
    collect_command_entries,
    feature_for_path,
)
from core.command_shortcuts import SHORTCUTS  # noqa: E402
from core.command_surface import DISCOVERY_12  # noqa: E402

# Leaf paths that overlap a hub or shortcut — candidates to de-emphasize in help.
OVERLAP_RULES: list[tuple[str, str]] = [
    ("warframe baro", "/baro shortcut"),
    ("warframe fissures", "/fissures shortcut"),
    ("warframe hub", "primary WF hub"),
    ("warframe status", "covered by /status + hub"),
    ("warframe world_state", "covered by /worth + hub"),
    ("general help_search", "/search shortcut"),
    ("community ticket", "/ticket shortcut"),
    ("trading trade", "/trade shortcut"),
    ("economy daily", "/daily if promoted"),
    ("economy wallet", "/wallet top-level if exists"),
]

NOTIFY_LEAVES = [
    p for p, _ in []  # filled at runtime
]


def _walk(group: app_commands.Group, prefix: list[str]) -> list[str]:
    paths: list[str] = []
    for cmd in group.commands:
        current = prefix + [cmd.name]
        if isinstance(cmd, app_commands.Group):
            paths.extend(_walk(cmd, current))
        elif isinstance(cmd, app_commands.Command):
            paths.append(" ".join(current))
    return paths


def _direct_subcount(group: app_commands.Group) -> int:
    return len(group.commands)


def _nested_subcount(group: app_commands.Group) -> int:
    total = 0
    for sub in group.commands:
        total += 1
        if isinstance(sub, app_commands.Group):
            total += len(sub.commands)
    return total


def main() -> None:
    bot = create_bot()
    entries = collect_command_entries(bot)
    leaf_count = len(entries)

    groups: list[tuple[str, int, int, list[str]]] = []
    standalone: list[str] = []
    oversized: list[str] = []
    headroom: list[str] = []

    for cmd in bot.tree.get_commands(guild=None):
        if isinstance(cmd, app_commands.ContextMenu):
            continue
        if isinstance(cmd, app_commands.Group):
            direct = _direct_subcount(cmd)
            nested = _nested_subcount(cmd)
            paths = _walk(cmd, [cmd.name])
            groups.append((cmd.name, direct, nested, paths))
            if direct > 25:
                oversized.append(f"/{cmd.name} — {direct} direct (OVER LIMIT)")
            elif direct > 23:
                headroom.append(f"/{cmd.name} — {direct}/25 direct")
            for sub in cmd.commands:
                if isinstance(sub, app_commands.Group) and len(sub.commands) > 25:
                    oversized.append(
                        f"/{cmd.name} {sub.name} — {len(sub.commands)}/25 nested"
                    )
        elif isinstance(cmd, app_commands.Command):
            standalone.append(cmd.name)

    top_level = len(groups) + len(standalone)
    total_grouped_leaves = sum(g[2] for g in groups)

    print("=" * 72)
    print("OBSIDIAN CLANBOT — SLASH COMMAND AUDIT")
    print("=" * 72)
    print()
    print("SUMMARY")
    print("-" * 72)
    print(f"  Top-level roots (groups + standalone):  {top_level} / 100 Discord cap")
    print(f"  Groups:                                 {len(groups)}")
    print(f"  Standalone top-level commands:          {len(standalone)}")
    print(f"  Total leaf commands (all paths):        {leaf_count}")
    print(f"  Grouped leaf count (nested walk):       {total_grouped_leaves}")
    print(f"  Registered shortcuts (aliases):         {len(SHORTCUTS)}")
    print()

    if oversized:
        print("CRITICAL — OVER 25 SUBCOMMANDS")
        print("-" * 72)
        for line in oversized:
            print(f"  !! {line}")
        print()
    else:
        print("OK — No group exceeds 25 direct subcommands.")
        print()

    if headroom:
        print("HEADROOM WARNINGS (23–25 direct subcommands)")
        print("-" * 72)
        for line in sorted(headroom):
            print(f"  !! {line}")
        print()

    print("PER-GROUP BREAKDOWN (direct / nested leaf count)")
    print("-" * 72)
    for name, direct, nested, _paths in sorted(groups, key=lambda x: -x[2]):
        bar = "#" * direct + "." * max(0, 25 - direct)
        flag = " !" if direct > 23 else ""
        print(f"  /{name:<14} direct {direct:2}/25  nested {nested:3}  [{bar}]{flag}")
    print()

    print("STANDALONE TOP-LEVEL COMMANDS")
    print("-" * 72)
    for name in sorted(standalone, key=str.lower):
        print(f"  /{name}")
    print()

    print("SHORTCUTS (same handler as nested command)")
    print("-" * 72)
    for path, name, desc in SHORTCUTS:
        print(f"  /{name:<12} -> /{' '.join(path)}")
    print()

    # Notify consolidation
    notify_paths = [p for p, _ in entries if "notify" in p.lower() or p.startswith("wfnotify")]
    print(f"NOTIFY-RELATED LEAVES ({len(notify_paths)}) — merge target: /wfnotify configure")
    print("-" * 72)
    for p in sorted(notify_paths):
        print(f"  /{p}")
    print()

    # Overlap / de-emphasize
    path_set = {p for p, _ in entries}
    print("OVERLAP / DE-EMPHASIZE CANDIDATES (keep working, hide from essentials)")
    print("-" * 72)
    for path, reason in OVERLAP_RULES:
        if path in path_set:
            print(f"  /{path:<35} — {reason}")
    print()

    # Mod-only volume
    mod_leaves = [p for p, _ in entries if p.split()[0] in MOD_ONLY_GROUPS]
    print(f"MOD/ADMIN-ONLY SURFACE ({len(mod_leaves)} leaves, hidden from member help)")
    print("-" * 72)
    by_root: dict[str, int] = defaultdict(int)
    for p in mod_leaves:
        by_root[p.split()[0]] += 1
    for root, count in sorted(by_root.items(), key=lambda x: -x[1]):
        print(f"  /{root:<14} {count} leaves")
    print()

    # Feature-toggleable
    toggleable: dict[str, list[str]] = defaultdict(list)
    for path, _ in entries:
        feat = feature_for_path(path)
        if feat:
            toggleable[feat].append(path)
    print("PER-GUILD FEATURE TOGGLES (runtime off via /admin features)")
    print("-" * 72)
    for feat, paths in sorted(toggleable.items(), key=lambda x: -len(x[1])):
        print(f"  {feat:<18} {len(paths):3} leaves")
    print()

    print("PROPOSED DISCOVERY 12 (public entry surface)")
    print("-" * 72)
    for entry in DISCOVERY_12:
        path = entry[0] if isinstance(entry, tuple) else entry
        ok = "OK" if path in path_set else "MISSING"
        print(f"  {ok}  /{path}")
    print()

    # Largest groups detail
    print("TOP 5 GROUPS — FULL LEAF LIST")
    print("-" * 72)
    for name, _direct, nested, paths in sorted(groups, key=lambda x: -x[2])[:5]:
        print(f"  /{name} ({nested} leaves):")
        for p in sorted(paths):
            print(f"    - {p}")
        print()

    print("RECOMMENDED NEXT STEPS")
    print("-" * 72)
    print("  1. Do not add roots — you have headroom but groups are tight.")
    print("  2. Fold new WF notify types into /wfnotify configure, not new leaves.")
    print("  3. Market only Discovery 12 in /start, bot bio, and discovery listing.")
    print("  4. Default /admin features off for gambling, pets, music on new installs.")
    print("  5. Deprecate duplicate /lfg paths and legacy notify subcommands over 2 releases.")
    print()


if __name__ == "__main__":
    main()
