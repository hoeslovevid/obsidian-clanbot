"""'Almost there' progress lines for profiles, bounties, voice, etc."""
from __future__ import annotations

from typing import Optional

import aiosqlite

from database import DB_PATH


async def voice_hours_to_next_role(guild_id: int, user_id: int) -> Optional[str]:
    """Hint voice-time milestones when playtime tracking is linked."""
    try:
        from database import get_linked_steam_id

        steam = await get_linked_steam_id(guild_id, user_id)
        if not steam:
            return None
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT playtime_hours FROM warframe_links WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        hours = float(row[0] or 0) if row else 0.0
        milestones = [100, 500, 1000, 2000, 5000]
        for req in milestones:
            if hours < req:
                need = max(0.1, req - hours)
                return f"**{need:.0f}h** playtime until **{req}h** Veteran milestone."
        return None
    except Exception:
        return None


async def bounties_remaining_line(guild_id: int, user_id: int) -> Optional[str]:
    try:
        from commands.economy.bounties import (
            BOUNTY_DEFS,
            _bounty_done,
            _get_bounty_progress,
            get_claimable_bounties,
        )
        from database import now_utc

        claimable = await get_claimable_bounties(guild_id, user_id)
        if claimable:
            n = len(claimable)
            return f"**{n}** {'bounty' if n == 1 else 'bounties'} ready to claim."
        progress = await _get_bounty_progress(guild_id, user_id)
        today = now_utc().date().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT bounty_type FROM economy_bounties WHERE guild_id=? AND user_id=? "
                "AND date(created_at)=? AND claimed=1",
                (guild_id, user_id, today),
            )
            claimed = {r[0] for r in await cur.fetchall()}
        left = [
            b for b in BOUNTY_DEFS
            if b["id"] not in claimed and not _bounty_done(b["id"], progress)
        ]
        if left:
            n = len(left)
            return f"**{n}** {'bounty' if n == 1 else 'bounties'} left today."
    except Exception:
        pass
    return None


async def onboarding_gap_line(guild_id: int, user_id: int) -> Optional[str]:
    try:
        from commands.general.onboarding import (
            ONBOARDING_STEP_NAMES,
            get_user_onboarding_progress,
        )

        done, steps = await get_user_onboarding_progress(guild_id, user_id)
        total = len(ONBOARDING_STEP_NAMES)
        if done >= total:
            return None
        missing = [s for s in ONBOARDING_STEP_NAMES if not steps.get(s)]
        if not missing:
            return None
        label = missing[0].replace("_", " ")
        return f"Onboarding **{done}/{total}** — next: **{label}** (`/onboarding resume`)."
    except Exception:
        return None


async def append_progress_nudge(
    body: str,
    guild_id: int,
    user_id: int,
    *,
    context: str = "general",
) -> str:
    """Append a single contextual nudge line if relevant."""
    line: Optional[str] = None
    if context in ("bounties", "daily", "claim"):
        line = await bounties_remaining_line(guild_id, user_id)
    elif context == "profile":
        line = await onboarding_gap_line(guild_id, user_id)
        if not line:
            line = await voice_hours_to_next_role(guild_id, user_id)
    elif context == "voice":
        line = await voice_hours_to_next_role(guild_id, user_id)
    elif context == "general":
        line = await onboarding_gap_line(guild_id, user_id)

    if line and line not in body:
        return f"{body.rstrip()}\n\n-# {line}"
    return body
