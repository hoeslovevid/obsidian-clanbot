#!/usr/bin/env python3
"""One-off utility: make the bot leave Discord servers in bulk.

Stop the main bot process (e.g. Railway) before running so the token is not in use.

Examples (from the obsidian_clanbot package root):

    python scripts/leave_all_guilds.py --dry-run
    python scripts/leave_all_guilds.py --yes
    python scripts/leave_all_guilds.py --yes --keep 123456789012345678
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import discord

# Allow `from core.config import …` when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _parse_keep(raw: str | None, default_guild_id: int) -> set[int]:
    keep: set[int] = set()
    if default_guild_id:
        keep.add(default_guild_id)
    if not raw:
        return keep
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            keep.add(int(part))
    return keep


async def _run(
    *,
    execute: bool,
    keep: set[int],
    delay: float,
) -> int:
    from core.config import TOKEN

    if not TOKEN:
        print("Missing DISCORD_TOKEN — set it in config/.env or the environment.")
        return 1

    left = 0
    skipped = 0
    failed = 0

    class LeaveBot(discord.Client):
        async def on_ready(self) -> None:
            nonlocal left, skipped, failed
            user = self.user
            print(f"Logged in as {user} ({user.id if user else '?'})")
            print(f"Guilds: {len(self.guilds)}")
            if not execute:
                print("\n--dry-run (pass --yes to leave)\n")

            for guild in list(self.guilds):
                if guild.id in keep:
                    print(f"  KEEP  {guild.name} ({guild.id})")
                    skipped += 1
                    continue
                if not execute:
                    print(f"  WOULD LEAVE  {guild.name} ({guild.id})")
                    continue
                try:
                    await guild.leave()
                    print(f"  LEFT  {guild.name} ({guild.id})")
                    left += 1
                except Exception as exc:
                    print(f"  FAIL  {guild.name} ({guild.id}): {exc}")
                    failed += 1
                if delay > 0:
                    await asyncio.sleep(delay)

            if execute:
                print(f"\nDone. left={left} kept={skipped} failed={failed}")
            else:
                would = len(self.guilds) - skipped
                print(f"\nWould leave {would} guild(s), keep {skipped}. Re-run with --yes to execute.")
            await self.close()

    async with LeaveBot(intents=discord.Intents.none()) as client:
        await client.start(TOKEN)

    return 1 if failed else 0


def main() -> None:
    from core.config import GUILD_ID

    parser = argparse.ArgumentParser(
        description="Leave Discord servers in bulk (stop the main bot first).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually leave servers (default is dry-run only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List guilds without leaving (default when --yes is omitted).",
    )
    parser.add_argument(
        "--keep",
        metavar="IDS",
        help="Comma-separated guild IDs to keep. GUILD_ID from .env is always kept when set.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between leaves (default: 1).",
    )
    args = parser.parse_args()

    execute = bool(args.yes)
    if execute:
        print("WARNING: This will remove the bot from servers. Stop Railway/production first.\n")
        confirm = input("Type LEAVE to confirm: ").strip()
        if confirm != "LEAVE":
            print("Aborted.")
            raise SystemExit(1)

    keep = _parse_keep(args.keep, GUILD_ID)
    if keep:
        print(f"Keeping guild ID(s): {', '.join(str(i) for i in sorted(keep))}\n")

    code = asyncio.run(
        _run(execute=execute, keep=keep, delay=max(0.0, args.delay)),
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
