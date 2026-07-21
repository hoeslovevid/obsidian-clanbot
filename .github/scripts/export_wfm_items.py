#!/usr/bin/env python3
"""Export a slim Warframe Market item catalog for the website.

Writes web/assets/wfm-items.json so market.html can search without Railway/CORS.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "assets" / "wfm-items.json"
WFM_ITEMS = "https://api.warframe.market/v2/items"
ASSET_BASE = "https://warframe.market/static/assets/"
UA = "ObsidianOverseerDeploy/1.0 (+https://obsidianoverseer.com; catalog export)"


def asset_url(path: str | None) -> str | None:
    if not path:
        return None
    path = str(path).lstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return ASSET_BASE + path


def main() -> int:
    req = urllib.request.Request(
        WFM_ITEMS,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Language": "en",
            "Platform": "pc",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)

    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        print("Unexpected WFM response shape", file=sys.stderr)
        return 1

    items = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        i18n = row.get("i18n") if isinstance(row.get("i18n"), dict) else {}
        en = i18n.get("en") if isinstance(i18n.get("en"), dict) else {}
        name = (en.get("name") or slug.replace("_", " ").title()).strip()
        items.append(
            {
                "slug": slug,
                "name": name,
                "thumb": asset_url(en.get("thumb")),
                "tags": row.get("tags") or [],
            }
        )

    items.sort(key=lambda it: (it["name"] or "").lower())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "ok": True,
                "source": "warframe.market/v2",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(items),
                "items": items,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(items)} items to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
