#!/usr/bin/env python3
"""Pre-deploy gate: fail if the slash command tree exceeds Discord limits.

Usage:
    python tools/check_command_tree.py

Exits 0 when the tree is within budget; 1 when any group has >25 subcommands
or other blocking issues are detected.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # Config import requires a token-shaped env var even though we never connect.
    os.environ.setdefault("TOKEN", "0" * 59)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    from bot.app import bot
    from core.command_tree_stats import collect_command_tree_stats

    stats = collect_command_tree_stats(bot)
    errors: list[str] = []

    if stats.oversized:
        errors.extend(f"Group over 25 subcommands: {line}" for line in stats.oversized)

    if len(stats.top_level_names) > 100:
        errors.append(f"Too many top-level commands: {len(stats.top_level_names)} (Discord max 100)")

    if errors:
        print("Command tree check FAILED:")
        for err in errors:
            print(f"  - {err}")
        if stats.headroom_warnings:
            print("\nHeadroom warnings (non-blocking):")
            for warn in stats.headroom_warnings[:12]:
                print(f"  - {warn}")
        return 1

    print(
        f"Command tree OK: {stats.top_level} top-level, "
        f"{stats.grouped_subcommands} grouped subcommands, "
        f"{len(stats.headroom_warnings)} headroom warning(s)"
    )
    for warn in stats.headroom_warnings[:8]:
        print(f"  warn: {warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
