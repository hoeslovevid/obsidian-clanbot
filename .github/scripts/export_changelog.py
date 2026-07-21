#!/usr/bin/env python3
"""Export core/changelog.py into web/assets/changelog.json for the website."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# core.config requires DISCORD_TOKEN at import time.
os.environ.setdefault("DISCORD_TOKEN", "changelog-export-placeholder")

from core.changelog import (  # noqa: E402
    CHANGELOG_HISTORY,
    CURRENT_RELEASE_CHANGES,
    CURRENT_RELEASE_DATE,
)
from core.config import BOT_VERSION  # noqa: E402

OUT = ROOT / "web" / "assets" / "changelog.json"
MAX_HISTORY = 12


def strip_md(text: str) -> str:
    """Light markdown → HTML-safe plain-ish text for the site."""
    s = text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    return s.strip()


def main() -> None:
    entries = [
        {
            "version": BOT_VERSION,
            "date": CURRENT_RELEASE_DATE,
            "current": True,
            "changes": [strip_md(c) for c in CURRENT_RELEASE_CHANGES],
        }
    ]
    for entry in CHANGELOG_HISTORY[:MAX_HISTORY]:
        if str(entry.get("version", "")) == BOT_VERSION:
            continue
        entries.append(
            {
                "version": str(entry.get("version", "")),
                "date": str(entry.get("date", "")),
                "current": False,
                "changes": [strip_md(c) for c in entry.get("changes", [])],
            }
        )

    payload = {"version": BOT_VERSION, "entries": entries}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(entries)} entries, version {BOT_VERSION})")


if __name__ == "__main__":
    main()
