"""Poll result helpers and auto-close summary (QoL #20)."""
from __future__ import annotations

import json
import logging
from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.utils import obsidian_embed, render_bar
from database import DB_PATH

logger = logging.getLogger(__name__)

_NUMBER_REACTIONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


async def fetch_poll_reaction_counts(message: discord.Message, options_list: list[str]) -> list[int]:
    counts: list[int] = []
    for i, _opt in enumerate(options_list):
        if i >= len(_NUMBER_REACTIONS):
            counts.append(0)
            continue
        reaction = discord.utils.get(message.reactions, emoji=_NUMBER_REACTIONS[i])
        counts.append(max(0, (reaction.count - 1) if reaction else 0))
    return counts


def build_poll_results_embed(
    question: str,
    options_list: list[str],
    counts: list[int],
    *,
    closed: bool = False,
    creator_name: Optional[str] = None,
) -> discord.Embed:
    total = sum(counts) or 0
    max_count = max(counts) if counts else 0
    lines: list[str] = []
    for idx, opt in enumerate(options_list):
        c = counts[idx] if idx < len(counts) else 0
        pct = (c / total * 100) if total > 0 else 0.0
        bar = render_bar(pct, length=12, show_pct=False)
        medal = ""
        if closed and total > 0 and c == max_count and max_count > 0:
            medal = " 🏆"
        emoji = _NUMBER_REACTIONS[idx] if idx < len(_NUMBER_REACTIONS) else f"{idx + 1}."
        lines.append(f"{emoji} **{opt}**{medal}\n{bar} **{pct:.0f}%** · {c} vote{'s' if c != 1 else ''}")
    title = "📊 Poll Closed" if closed else "📊 Poll"
    desc = f"**{question}**\n\n" + "\n".join(lines)
    if total == 0:
        desc += "\n\n_No votes were cast._"
    elif closed:
        winners = [options_list[i] for i, c in enumerate(counts) if c == max_count and max_count > 0]
        if len(winners) == 1:
            desc += f"\n\n**Winner:** {winners[0]} ({max_count} vote{'s' if max_count != 1 else ''})"
        elif winners:
            desc += f"\n\n**Tie:** " + ", ".join(f"**{w}**" for w in winners)
        desc += f"\n\n**Total votes:** {total}"
    embed = obsidian_embed(title, desc, color=discord.Color.gold() if closed else discord.Color.blue())
    footer = "Final results" if closed else "Live results — react to vote"
    if creator_name:
        footer = f"{footer} • Poll by {creator_name}"
    embed.set_footer(text=footer)
    return embed


async def close_expired_poll(bot, row: tuple) -> None:
    """Mark poll closed and post final summary embed on the poll message."""
    poll_id, guild_id, channel_id, message_id, question, options_json, creator_id = row[:7]
    try:
        options_list = json.loads(options_json)
    except (TypeError, json.JSONDecodeError):
        options_list = []

    guild = bot.get_guild(int(guild_id))
    if not guild:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE polls SET closed=1 WHERE id=?", (poll_id,))
            await db.commit()
        return

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE polls SET closed=1 WHERE id=?", (poll_id,))
            await db.commit()
        return

    creator_name: Optional[str] = None
    creator = guild.get_member(int(creator_id)) if creator_id else None
    if creator:
        creator_name = creator.display_name

    try:
        message = await channel.fetch_message(int(message_id))
        counts = await fetch_poll_reaction_counts(message, options_list)
        embed = build_poll_results_embed(
            question, options_list, counts, closed=True, creator_name=creator_name
        )
        await message.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        logger.debug("[poll] close edit failed for %s: %s", message_id, exc)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE polls SET closed=1 WHERE id=?", (poll_id,))
        await db.commit()
