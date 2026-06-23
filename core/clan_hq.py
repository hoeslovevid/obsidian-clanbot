"""Member-facing Clan HQ dashboard embed."""
from __future__ import annotations

import aiosqlite
import discord

from core.utils import is_mod, obsidian_embed, EMBED_COLORS
from database import DB_PATH


async def _user_baro_wishlist_line(guild_id: int, user_id: int, baro_inventory: list) -> str | None:
    if not baro_inventory:
        return None
    inv_names = {
        str(i.get("item") or i.get("name") or "").strip().lower()
        for i in baro_inventory
        if i
    }
    inv_names.discard("")
    if not inv_names:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT item_name FROM baro_wishlist WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        wish = [str(r[0]) for r in await cur.fetchall()]
    hits = [n for n in wish if n.strip().lower() in inv_names]
    if not hits:
        return None
    shown = ", ".join(f"**{h}**" for h in hits[:4])
    extra = f" +{len(hits) - 4} more" if len(hits) > 4 else ""
    return f"⭐ Your wishlist: {shown}{extra}"


async def _twitch_live_summary(guild_id: int) -> str | None:
    from core.wf_hub_extras import get_twitch_streaming_line

    return await get_twitch_streaming_line(guild_id)


async def build_clan_hq_embed(
    guild: discord.Guild,
    *,
    client=None,
    user_id: int | None = None,
    viewer: discord.Member | None = None,
) -> discord.Embed:
    """One-glance clan hub: LFG, events, Baro, live streamers."""
    lines: list[str] = [f"**{guild.name}** — your clan at a glance\n"]

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild.id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            """
            SELECT title, start_ts FROM events
            WHERE guild_id=? AND COALESCE(ended, 0)=0 AND start_ts > ?
            ORDER BY start_ts ASC LIMIT 3
            """,
            (guild.id, int(__import__("time").time())),
        )
        events = await cur.fetchall()
        cur = await db.execute(
            "SELECT streamer_name FROM twitch_streamers WHERE guild_id=? LIMIT 8",
            (guild.id,),
        )
        streamers = [r[0] for r in await cur.fetchall()]

    lines.append(f"🤝 **Open LFG posts:** {open_lfg} — `/lfg list`")
    if events:
        ev_lines = []
        for title, start_ts in events:
            ev_lines.append(f"• **{str(title)[:40]}** <t:{int(start_ts)}:R>")
        lines.append("📅 **Upcoming events:**\n" + "\n".join(ev_lines))
    else:
        lines.append("📅 **Events:** none scheduled — `/events`")

    baro_inventory: list = []
    try:
        from api.warframe_api import get_baro_status

        active, data = await get_baro_status()
        if active and data:
            loc = data.get("location", "?")
            baro_inventory = data.get("inventory") or data.get("Inventory") or []
            line = f"🛒 **Baro:** active at **{loc}** — `/warframe baro`"
            if user_id:
                wish_line = await _user_baro_wishlist_line(guild.id, user_id, baro_inventory)
                if wish_line:
                    line += f"\n{wish_line}"
            lines.append(line)
        else:
            lines.append("🛒 **Baro:** away — `/warframe baro`")
    except Exception:
        lines.append("🛒 **Baro:** `/warframe baro`")

    live_line = await _twitch_live_summary(guild.id)
    if live_line:
        lines.append(live_line)
    elif streamers:
        live_hint = ", ".join(f"`{s}`" for s in streamers[:4])
        lines.append(f"📺 **Monitored streamers:** {live_hint} (offline)")

    if user_id:
        try:
            from core.schedule_bridge import gather_personal_schedule, format_schedule_lines

            schedule = await gather_personal_schedule(guild.id, user_id)
            personal = format_schedule_lines(guild.id, schedule)
            if personal:
                lines.append("\n**Your next 24h:**\n" + "\n".join(personal[:5]))
        except Exception:
            pass

    lines.append("\n-# `/menu` · `/today` · `/notifications` · `/warframe hub`")

    if viewer and is_mod(viewer):
        try:
            from commands.general.setup_status import setup_health_line

            lines.append(f"\n🧭 _Staff:_ {await setup_health_line(guild)}")
        except Exception:
            pass

    footer = "Tap **Update data** to refresh · `/status` for API health"
    try:
        from core.wf_copy import merge_wf_footer

        footer = merge_wf_footer(footer, "warframe:baro")
    except Exception:
        pass

    return obsidian_embed(
        "🏠 Clan HQ",
        "\n".join(lines),
        color=EMBED_COLORS.get("warframe", discord.Color.dark_grey()),
        footer=footer,
        client=client,
    )
