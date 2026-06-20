"""Unified 'Your day' snapshot for /today and optional /me chips."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite
import discord

from core.utils import format_number, pluralize
from database import DB_PATH


async def gather_today_data(
    guild_id: int,
    user_id: int,
    *,
    bot: Optional[discord.Client] = None,
) -> dict[str, Any]:
    """Collect urgency-sorted facts for the today panel."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    out: dict[str, Any] = {
        "daily_claimed": False,
        "streak": 0,
        "freeze_available": True,
        "bounties_claimable": 0,
        "bounty_coins": 0,
        "baro_active": False,
        "baro_location": "",
        "baro_wishlist_hits": [],
        "lfg_hosting": [],
        "lfg_joined": [],
        "events_today": [],
        "pet_needs_care": False,
        "pet_line": "",
        "investment_ready": False,
        "reminders_pending": 0,
        "onboarding_done": 0,
        "onboarding_total": 0,
    }

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT last_claim_date, streak_days, freeze_used_month FROM daily_claims "
            "WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            out["daily_claimed"] = row[0] == today_iso
            out["streak"] = int(row[1] or 0)
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            out["freeze_available"] = (row[2] if len(row) > 2 else None) != month

        try:
            cur = await db.execute(
                "SELECT COUNT(*) FROM reminders WHERE guild_id=? AND user_id=? AND sent=0",
                (guild_id, user_id),
            )
            r = await cur.fetchone()
            if r:
                out["reminders_pending"] = int(r[0] or 0)
        except Exception:
            pass

        cur = await db.execute(
            """
            SELECT id, mission_type, max_players FROM lfg_posts
            WHERE guild_id=? AND creator_id=? AND status='OPEN'
            ORDER BY created_at DESC LIMIT 3
            """,
            (guild_id, user_id),
        )
        out["lfg_hosting"] = [(int(r[0]), str(r[1]), int(r[2])) for r in await cur.fetchall()]

        cur = await db.execute(
            """
            SELECT p.id, p.mission_type, p.max_players
            FROM lfg_rsvps r
            JOIN lfg_posts p ON p.id = r.lfg_id
            WHERE p.guild_id=? AND r.user_id=? AND r.response='JOIN' AND p.status='OPEN'
              AND p.creator_id != ?
            ORDER BY r.created_at DESC LIMIT 3
            """,
            (guild_id, user_id, user_id),
        )
        out["lfg_joined"] = [(int(r[0]), str(r[1]), int(r[2])) for r in await cur.fetchall()]

        try:
            cur = await db.execute(
                """
                SELECT e.title, e.start_ts FROM events e
                JOIN event_rsvps r ON r.guild_id=e.guild_id AND r.message_id=e.message_id
                WHERE e.guild_id=? AND r.user_id=? AND r.response IN ('GOING','MAYBE')
                  AND e.start_ts IS NOT NULL AND e.start_ts > 0
                ORDER BY e.start_ts LIMIT 5
                """,
                (guild_id, user_id),
            )
            today = datetime.now(timezone.utc).date()
            for title, start_ts in await cur.fetchall():
                try:
                    start_dt = datetime.fromtimestamp(int(start_ts), tz=timezone.utc)
                    if start_dt.date() == today:
                        out["events_today"].append((str(title or "Event"), int(start_ts)))
                except Exception:
                    pass
        except Exception:
            pass

    try:
        from commands.economy.bounties import get_claimable_bounties

        claimable = await get_claimable_bounties(guild_id, user_id)
        out["bounties_claimable"] = len(claimable)
        out["bounty_coins"] = sum(b["reward"] for b in claimable)
    except Exception:
        pass

    try:
        from api.warframe_api import get_baro_status

        active, baro = await get_baro_status()
        out["baro_active"] = bool(active and baro)
        if baro:
            out["baro_location"] = str(baro.get("location") or "")
            inv = baro.get("inventory") or []
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT item_name FROM baro_wishlist WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                wish = {str(r[0]).strip().lower() for r in await cur.fetchall()}
            inv_names = {
                str(i.get("item") or i.get("name") or "").strip().lower() for i in inv if i
            }
            out["baro_wishlist_hits"] = [n for n in wish if n in inv_names][:5]
    except Exception:
        pass

    try:
        from commands.general.profile import get_user_profile_data

        pdata = await get_user_profile_data(guild_id, user_id)
        if pdata.get("pet"):
            from commands.economy.pets import (
                HAPPINESS_DECAY_PER_HOUR,
                HUNGER_DECAY_PER_HOUR,
                _apply_decay,
                get_pet_emoji,
            )

            pet = pdata["pet"]
            h = _apply_decay(
                pet.get("hunger") or 100,
                pet.get("last_fed"),
                pet.get("created_at"),
                HUNGER_DECAY_PER_HOUR,
            )
            hp = _apply_decay(
                pet.get("happiness") or 100,
                pet.get("last_played"),
                pet.get("created_at"),
                HAPPINESS_DECAY_PER_HOUR,
            )
            out["pet_needs_care"] = h < 50 or hp < 50
            emoji = get_pet_emoji(pet.get("type"))
            name = pet.get("name") or pet.get("type") or "Pet"
            out["pet_line"] = f"{emoji} **{name}** — hunger {h}/100 · happy {hp}/100"
    except Exception:
        pass

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT maturity_date, collected FROM investments "
                "WHERE guild_id=? AND user_id=? AND collected=0 ORDER BY invested_at DESC LIMIT 1",
                (guild_id, user_id),
            )
            inv = await cur.fetchone()
            if inv:
                mat = datetime.fromisoformat(str(inv[0]).replace("Z", "+00:00"))
                out["investment_ready"] = datetime.now(timezone.utc) >= mat
    except Exception:
        pass

    try:
        from commands.general.onboarding import ONBOARDING_STEP_NAMES, get_user_onboarding_progress

        done, _ = await get_user_onboarding_progress(guild_id, user_id)
        out["onboarding_done"] = done
        out["onboarding_total"] = len(ONBOARDING_STEP_NAMES)
    except Exception:
        pass

    return out


def build_today_fields(data: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Turn gathered data into embed fields, urgency first."""
    fields: list[tuple[str, str, bool]] = []

    if not data["daily_claimed"]:
        streak = data["streak"]
        freeze = " · freeze available" if data["freeze_available"] and streak > 0 else ""
        fields.append(("🎁 Daily", f"**Unclaimed** — `/daily`{freeze}", True))
    else:
        tomorrow = (
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        fields.append(
            ("🎁 Daily", f"✅ Claimed · next <t:{int(tomorrow.timestamp())}:R>", True),
        )

    if data["bounties_claimable"]:
        fields.append(
            (
                "🎯 Bounties",
                f"**{data['bounties_claimable']}** ready "
                f"(**{format_number(data['bounty_coins'])}** coins) — `/claim`",
                True,
            ),
        )

    if data["baro_active"]:
        loc = data["baro_location"] or "Relay"
        line = f"Baro at **{loc}** — `/baro`"
        if data["baro_wishlist_hits"]:
            hits = ", ".join(f"**{h}**" for h in data["baro_wishlist_hits"])
            line += f"\nWishlist match: {hits}"
        fields.append(("🛒 Baro", line, True))

    if data["investment_ready"]:
        fields.append(("📈 Investment", "✅ Ready to collect — `/economy invest_collect`", True))

    if data["pet_needs_care"] and data["pet_line"]:
        fields.append(("🐾 Pet", data["pet_line"] + "\n`/pets feed` · `/pets play`", True))

    if data["lfg_hosting"]:
        lines = [f"**{m}** (host, max {mx})" for _, m, mx in data["lfg_hosting"]]
        fields.append(("🤝 Your LFG", "\n".join(lines) + "\n`/lfg list`", False))

    if data["lfg_joined"]:
        lines = [f"**{m}** (joined)" for _, m, _ in data["lfg_joined"]]
        fields.append(("🤝 Squads", "\n".join(lines), False))

    if data["events_today"]:
        lines = [f"**{t}** <t:{ts}:t>" for t, ts in data["events_today"]]
        fields.append(("📅 Events today", "\n".join(lines), False))

    if data["reminders_pending"]:
        n = data["reminders_pending"]
        fields.append(
            ("🔔 Reminders", f"**{n}** pending — `/general remind_list`", True),
        )

    if data["onboarding_total"] and data["onboarding_done"] < data["onboarding_total"]:
        d, t = data["onboarding_done"], data["onboarding_total"]
        fields.append(("🎓 Onboarding", f"**{d}/{t}** — `/onboarding resume`", True))

    if not fields:
        fields.append(("✨ All clear", "Nothing urgent — explore `/menu` or `/warframe hub`", False))

    return fields


def today_footer(data: dict[str, Any]) -> str:
    if not data["daily_claimed"]:
        return "🎁 Daily unclaimed — run `/daily` first"
    if data["pet_needs_care"]:
        return "🐾 Pet needs care — `/pets feed`"
    if data["bounties_claimable"]:
        return f"🎯 {data['bounties_claimable']} {pluralize(data['bounties_claimable'], 'bounty')} ready"
    if data["baro_active"] and data["baro_wishlist_hits"]:
        return "🛒 Baro has wishlist items — check `/baro`"
    return "Your day at a glance · `/me` for full snapshot"
