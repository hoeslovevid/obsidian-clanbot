"""Warframe hub helpers — daily ops snippets, relic planner, Baro wishlist, Twitch line."""
from __future__ import annotations

import os
from typing import Optional

import aiosqlite
import discord

from database import DB_PATH, now_utc


def format_daily_ops_snippet(
    sp: Optional[dict],
    arb: Optional[dict],
    nw: Optional[dict],
) -> str:
    """One-line Steel Path / Arbitration / Nightwave summary for the hub."""
    parts: list[str] = []
    if sp:
        reward = sp.get("currentReward", {})
        name = reward.get("name", "?") if isinstance(reward, dict) else str(reward or "?")
        parts.append(f"SP: **{name}**")
    if arb:
        node = arb.get("node", "?")
        parts.append(f"Arb: **{node}**")
    if nw:
        daily = nw.get("dailyChallenges", []) or []
        if daily and isinstance(daily, list):
            title = (daily[0].get("title") or daily[0].get("desc") or "?")[:40]
            parts.append(f"NW: {title}")
        elif nw.get("season") is not None:
            parts.append(f"NW S{nw.get('season')}")
    return " · ".join(parts) if parts else "—"


def format_relic_planner_hint(fissures: list | None) -> str:
    """Lightweight relic/fissure planner — top tiers by count."""
    if not fissures:
        return "No active fissures — check `/warframe fissures`"
    tiers: dict[str, int] = {}
    for f in fissures:
        if f.get("expired"):
            continue
        tier = str(f.get("tier", "?")).replace("Void ", "").strip() or "?"
        tiers[tier] = tiers.get(tier, 0) + 1
    if not tiers:
        return "No active fissures"
    top = sorted(tiers.items(), key=lambda x: -x[1])[:4]
    line = ", ".join(f"**{t}**×{c}" for t, c in top)
    return f"{line} · `/warframe fissures` for nodes"


async def get_baro_wishlist_overlap(guild_id: int, baro_inventory: list | None) -> str | None:
    """Return overlap line when members want items Baro is selling."""
    if not baro_inventory:
        return None
    inv_names = {
        str(item.get("item") or item.get("name") or "").strip().lower()
        for item in baro_inventory
        if item
    }
    inv_names.discard("")
    if not inv_names:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT item_name, COUNT(*) FROM baro_wishlist WHERE guild_id=? GROUP BY item_name",
            (guild_id,),
        )
        rows = await cur.fetchall()
    hits: list[str] = []
    for item_name, count in rows:
        if item_name.strip().lower() in inv_names:
            hits.append(f"**{item_name}** ({count})")
    if not hits:
        return None
    shown = ", ".join(hits[:5])
    extra = f" +{len(hits) - 5} more" if len(hits) > 5 else ""
    return f"🛒 Clan wants: {shown}{extra}"


async def dm_baro_wishlist_matches(
    bot,
    guild_id: int,
    baro_inventory: list | None,
    *,
    location: str = "",
) -> None:
    """DM users whose Baro wishlist items appear in the current inventory."""
    if not baro_inventory:
        return
    inv_names = {
        str(item.get("item") or item.get("name") or "").strip().lower()
        for item in baro_inventory
        if item
    }
    inv_names.discard("")
    if not inv_names:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, item_name FROM baro_wishlist WHERE guild_id=?",
            (guild_id,),
        )
        rows = await cur.fetchall()
    by_user: dict[int, list[str]] = {}
    for user_id, item_name in rows:
        if item_name.strip().lower() in inv_names:
            by_user.setdefault(int(user_id), []).append(item_name)
    if not by_user:
        return
    guild = bot.get_guild(guild_id)
    loc = f" at **{location}**" if location else ""
    from core.utils import obsidian_embed

    for user_id, items in by_user.items():
        member = guild.get_member(user_id) if guild else None
        user = member or bot.get_user(user_id)
        if not user:
            continue
        shown = ", ".join(f"**{n}**" for n in items[:6])
        extra = f" +{len(items) - 6} more" if len(items) > 6 else ""
        embed = obsidian_embed(
            "🛒 Baro wishlist match",
            f"Baro is here{loc} with items on your wishlist:\n{shown}{extra}\n\n"
            "`/warframe hub` · `/baro` · `/lfg` for Baro farming squads",
            color=discord.Color.gold(),
            client=bot,
        )
        from views.baro_wishlist_dm import BaroWishlistDMView
        from core.dm_coalesce import queue_coalesced_dm

        view = BaroWishlistDMView(guild_id)
        try:
            bot.add_view(view)
        except Exception:
            pass
        try:
            from core.quiet_hours import in_quiet_hours

            if await in_quiet_hours(guild_id, user_id):
                continue
            await queue_coalesced_dm(
                bot, guild_id, user_id, "Baro wishlist", embed, view=view,
            )
        except Exception:
            pass


async def toggle_baro_wishlist(guild_id: int, user_id: int, item_name: str) -> tuple[bool, str]:
    """Add or remove a Baro wishlist entry. Returns (added, message)."""
    name = item_name.strip()[:120]
    if not name:
        return False, "Item name required."
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM baro_wishlist WHERE guild_id=? AND user_id=? AND item_name=?",
            (guild_id, user_id, name),
        )
        if await cur.fetchone():
            await db.execute(
                "DELETE FROM baro_wishlist WHERE guild_id=? AND user_id=? AND item_name=?",
                (guild_id, user_id, name),
            )
            await db.commit()
            return False, f"Removed **{name}** from your Baro wishlist."
        await db.execute(
            "INSERT INTO baro_wishlist (guild_id, user_id, item_name, created_at) VALUES (?,?,?,?)",
            (guild_id, user_id, name, now_utc().isoformat()),
        )
        await db.commit()
    return True, f"Added **{name}** to your Baro wishlist."


async def get_twitch_streaming_line(guild_id: int) -> str | None:
    """Return a one-line 'who's streaming' hint when Twitch is configured."""
    if not os.getenv("TWITCH_CLIENT_ID") or not os.getenv("TWITCH_CLIENT_SECRET"):
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='twitch_streamers'"
        )
        if not await cur.fetchone():
            return None
        cur = await db.execute(
            "SELECT streamer_name FROM twitch_streamers WHERE guild_id=? AND enabled=1 LIMIT 8",
            (guild_id,),
        )
        streamers = [r[0] for r in await cur.fetchall()]
    if not streamers:
        return None
    try:
        from commands.general.twitch import get_twitch_access_token, check_twitch_stream

        token = await get_twitch_access_token()
        if not token:
            return None
        live: list[str] = []
        for name in streamers:
            data = await check_twitch_stream(name, token)
            if data:
                live.append(f"[{name}](https://twitch.tv/{name})")
        if live:
            return f"📺 Live now: {', '.join(live[:3])}"
    except Exception:
        pass
    return None
