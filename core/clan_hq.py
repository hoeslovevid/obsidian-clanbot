"""Member-facing Clan HQ dashboard embed."""
from __future__ import annotations

import aiosqlite
import discord

from core.utils import obsidian_embed, EMBED_COLORS
from database import DB_PATH


async def build_clan_hq_embed(guild: discord.Guild, *, client=None) -> discord.Embed:
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
            "SELECT streamer_name FROM twitch_streamers WHERE guild_id=? LIMIT 5",
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

    try:
        from api.warframe_api import get_baro_status

        active, data = await get_baro_status()
        if active and data:
            loc = data.get("location", "?")
            lines.append(f"🛒 **Baro:** active at **{loc}** — `/warframe baro`")
        else:
            lines.append("🛒 **Baro:** away — `/warframe baro`")
    except Exception:
        lines.append("🛒 **Baro:** `/warframe baro`")

    if streamers:
        live_hint = ", ".join(f"`{s}`" for s in streamers[:4])
        lines.append(f"📺 **Monitored streamers:** {live_hint}")
    lines.append("\n-# `/menu` · `/today` · `/notifications` · `/warframe hub`")

    return obsidian_embed(
        "🏠 Clan HQ",
        "\n".join(lines),
        color=EMBED_COLORS.get("warframe", discord.Color.dark_grey()),
        client=client,
    )
