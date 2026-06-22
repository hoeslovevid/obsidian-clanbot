"""Persistent `/claim` hub — embed builder + refresh payload."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord

from core.db import open_db
from core.utils import EMBED_COLORS, format_number, obsidian_embed
from database import now_utc


async def build_claim_hub(
    guild_id: int,
    user_id: int,
    *,
    client=None,
    guild_name: str | None = None,
) -> tuple[discord.Embed, dict, dict[str, bool]]:
    """Return embed, refresh payload, and action flags for panel buttons."""
    from core.command_mentions import command_mention
    from core.embed_prefs import embed_kwargs

    ek = await embed_kwargs(guild_id, user_id)
    lines: list[str] = []
    daily_ready = False
    bounty_ready = False
    invest_ready = False

    today = datetime.now(timezone.utc).date().isoformat()
    async with open_db() as db:
        cur = await db.execute(
            "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
    if not row or row[0] != today:
        daily_ready = True
        lines.append(f"🎁 **Daily** — ✅ ready · {command_mention('daily', fallback='`/daily`')}")
    else:
        tomorrow = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ) + timedelta(days=1)
        lines.append(f"🎁 **Daily** — claimed · next <t:{int(tomorrow.timestamp())}:R>")

    try:
        from commands.economy.bounties import get_claimable_bounties

        claimable = await get_claimable_bounties(guild_id, user_id)
        if claimable:
            total = sum(b["reward"] for b in claimable)
            bounty_ready = True
            lines.append(
                f"🎯 **Bounties** — {len(claimable)} ready ({format_number(total)} coins)"
            )
        else:
            midnight = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0,
            ) + timedelta(days=1)
            lines.append(f"🎯 **Bounties** — none ready · reset <t:{int(midnight.timestamp())}:R>")
    except Exception:
        lines.append("🎯 **Bounties** — unavailable")

    try:
        from commands.economy.pets import (
            HAPPINESS_DECAY_PER_HOUR,
            HUNGER_DECAY_PER_HOUR,
            _apply_decay,
        )

        async with open_db() as db:
            cur = await db.execute(
                "SELECT hunger, happiness, last_fed, last_played, created_at, name "
                "FROM pets WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            pet = await cur.fetchone()
        if pet:
            h = _apply_decay(pet[0] or 100, pet[2], pet[4], HUNGER_DECAY_PER_HOUR)
            hp = _apply_decay(pet[1] or 100, pet[3], pet[4], HAPPINESS_DECAY_PER_HOUR)
            if h < 50 or hp < 50:
                lines.append(f"🐾 **{pet[5] or 'Pet'}** — needs care")
            else:
                lines.append(f"🐾 **{pet[5] or 'Pet'}** — ✅ doing fine")
    except Exception:
        pass

    async with open_db() as db:
        cur = await db.execute(
            "SELECT id, maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 "
            "ORDER BY maturity_date ASC LIMIT 1",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
    if row:
        _invest_id, mat_raw = row[0], row[1]
        try:
            mat = datetime.fromisoformat(str(mat_raw).replace("Z", "+00:00"))
            if mat.tzinfo is None:
                mat = mat.replace(tzinfo=timezone.utc)
            if mat <= now_utc():
                invest_ready = True
                lines.append("📈 **Investment** — ✅ matured and ready to collect")
            else:
                lines.append(f"📈 **Investment** — matures <t:{int(mat.timestamp())}:R>")
        except Exception:
            pass

    body = "\n".join(lines) or "Nothing to claim right now."
    try:
        from core.next_hints import get_next_step_hint

        hint = await get_next_step_hint(guild_id, user_id, "claim")
        if hint:
            body += f"\n\n-# {hint}"
    except Exception:
        pass

    embed = obsidian_embed(
        "💰 Claim Hub",
        body,
        color=EMBED_COLORS.get("economy", discord.Color.gold()),
        footer="Daily auto-claims bounties when you run `/daily` · **Update data** refreshes",
        client=client,
        **ek,
    )
    payload = {"guild_id": guild_id, "user_id": user_id}
    flags = {
        "daily_ready": daily_ready,
        "bounty_ready": bounty_ready,
        "invest_ready": invest_ready,
        "has_actions": daily_ready or bounty_ready or invest_ready,
    }
    return embed, payload, flags
