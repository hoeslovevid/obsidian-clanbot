#!/usr/bin/env python3
"""Fetch live server/user counts from the Discord API and write bot-stats.json.

Uses DISCORD_TOKEN (same bot token as Railway). Does not call Railway, so it
works even when the public API is rate-limited.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://discord.com/api/v10"
OUT_PATH = Path("web/assets/bot-stats.json")
USER_AGENT = "ObsidianOverseerStats (https://obsidianoverseer.com; +github-actions)"


def _request(url: str, token: str, retries: int = 5) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    delay = 1.5
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code == 429 and attempt + 1 < retries:
                retry_after = float(exc.headers.get("Retry-After") or delay)
                print(f"rate limited, sleeping {retry_after}s…", file=sys.stderr)
                time.sleep(retry_after)
                delay = min(delay * 2, 30)
                continue
            raise SystemExit(f"Discord API {exc.code} for {url}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise SystemExit(f"Discord API network error for {url}: {exc}") from exc
    raise SystemExit(f"Discord API failed for {url}")


def list_guilds(token: str) -> list[dict]:
    guilds: list[dict] = []
    after: str | None = None
    while True:
        url = f"{API}/users/@me/guilds?limit=200"
        if after:
            url += f"&after={after}"
        batch = _request(url, token)
        if not isinstance(batch, list):
            raise SystemExit(f"Unexpected guilds payload: {batch!r}")
        guilds.extend(batch)
        if len(batch) < 200:
            break
        after = batch[-1]["id"]
        time.sleep(0.3)
    return guilds


def guild_member_count(token: str, guild_id: str) -> int:
    data = _request(f"{API}/guilds/{guild_id}?with_counts=true", token)
    if not isinstance(data, dict):
        return 0
    return int(data.get("approximate_member_count") or 0)


def main() -> int:
    token = (os.environ.get("DISCORD_TOKEN") or "").strip()
    if not token:
        print(
            "Missing DISCORD_TOKEN.\n"
            "Add it as a GitHub Actions secret (same value as Railway DISCORD_TOKEN):\n"
            "  Repo → Settings → Secrets and variables → Actions → New repository secret\n"
            "  Name: DISCORD_TOKEN",
            file=sys.stderr,
        )
        return 1

    guilds = list_guilds(token)
    user_count = 0
    for i, guild in enumerate(guilds):
        user_count += guild_member_count(token, str(guild["id"]))
        if i + 1 < len(guilds):
            time.sleep(0.35)

    data = {
        "guild_count": len(guilds),
        "user_count": user_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = None
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None

    # Ignore timestamp when deciding whether to commit.
    if (
        existing
        and existing.get("guild_count") == data["guild_count"]
        and existing.get("user_count") == data["user_count"]
    ):
        print("No change:", json.dumps(data))
        # Still refresh updated_at so the file stays "fresh" for debugging.
        if existing.get("updated_at") != data["updated_at"]:
            OUT_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print("Refreshed updated_at only")
        return 0

    OUT_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Updated:", json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
