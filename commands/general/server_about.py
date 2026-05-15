"""Item 93 — `/server about` identity card.

Lightweight read-only command that summarises the server (members, age,
owner, top contributors, boost level). Heavy queries are cached for
10 minutes per guild to keep the command snappy in big servers.
"""
from __future__ import annotations

import time
from typing import Optional

import aiosqlite  # type: ignore
import discord
from discord import app_commands

from core.utils import (
    EMBED_COLORS,
    error_embed,
    format_number,
    obsidian_embed,
    pluralize,
)
from database import DB_PATH


_CACHE_TTL = 10 * 60  # 10 minutes
_CACHE: dict[int, tuple[float, discord.Embed]] = {}


async def _build_about_embed(guild: discord.Guild, client: discord.Client) -> discord.Embed:
    """Build the identity-card embed (heavy work; cached by caller)."""
    total_members = guild.member_count or len(guild.members)
    online_members = sum(
        1 for m in guild.members
        if m.status not in (discord.Status.offline, discord.Status.invisible) and not m.bot
    )
    voice_members = sum(
        1 for m in guild.members if m.voice and m.voice.channel is not None
    )

    created = guild.created_at
    created_ts = int(created.timestamp())
    age_days = max(0, (discord.utils.utcnow() - created).days)
    age_label = (
        f"{age_days // 365}y {age_days % 365}d" if age_days >= 365
        else f"{age_days} {pluralize(age_days, 'day')}"
    )

    owner_line = guild.owner.mention if guild.owner else "—"

    boost_level = guild.premium_tier
    boost_count = guild.premium_subscription_count or 0

    fields: list[tuple[str, str, bool]] = [
        ("👥 Members", f"**{format_number(total_members)}** total\n"
                       f"🟢 {format_number(online_members)} online · 🔊 {format_number(voice_members)} in voice", True),
        ("📅 Created", f"<t:{created_ts}:D>\n_{age_label} old_", True),
        ("👑 Owner", owner_line, True),
        ("✨ Boosts", f"Level **{boost_level}** · {boost_count} {pluralize(boost_count, 'boost')}", True),
    ]

    # Top contributors (by weekly activity score)
    top_active_lines: list[str] = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT user_id, weekly_score
                FROM activity_stats
                WHERE guild_id=? AND weekly_score > 0
                ORDER BY weekly_score DESC
                LIMIT 3
                """,
                (guild.id,),
            )
            rows = await cur.fetchall()
        for user_id, score in rows:
            member = guild.get_member(int(user_id))
            label = member.mention if member else f"`{user_id}`"
            top_active_lines.append(f"{label} — **{format_number(int(score or 0))}** pts")
    except Exception:
        top_active_lines = []
    if top_active_lines:
        fields.append(("🏆 Top contributors (this week)", "\n".join(top_active_lines), False))

    # Most active channels in the last 7 days — best-effort, since the
    # activity_log table isn't keyed on channel_id. We fall back to
    # `last_message_id` proximity (purely heuristic) and omit gracefully
    # when nothing meaningful surfaces.
    try:
        recent_channels = sorted(
            [c for c in guild.text_channels if c.last_message_id],
            key=lambda c: c.last_message_id or 0,
            reverse=True,
        )[:3]
        if recent_channels:
            fields.append((
                "💬 Recently active channels",
                "\n".join(f"<#{c.id}>" for c in recent_channels),
                False,
            ))
    except Exception:
        pass

    desc_lines = [f"**{guild.name}**"]
    if guild.description:
        desc_lines.append(f"_{guild.description}_")

    embed = obsidian_embed(
        f"📇 About {guild.name}",
        "\n\n".join(desc_lines),
        color=EMBED_COLORS["community"],
        thumbnail=guild.icon.url if guild.icon else None,
        image=guild.banner.url if guild.banner else None,
        fields=fields,
        client=client,
        footer=f"Server ID: {guild.id}",
    )
    return embed


def setup(bot, group=None):
    """Register `/server about`. Always uses a dedicated top-level `/server`
    group (the existing `general_group` is full)."""
    server_group = app_commands.Group(name="server", description="📇 Server identity & quick facts.")

    @server_group.command(name="about", description="Show this server's identity card (cached 10m).")
    async def server_about(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Run this inside a Discord server.", client=interaction.client),
                ephemeral=True,
            )
        guild = interaction.guild

        await interaction.response.defer()

        cached = _CACHE.get(guild.id)
        embed: Optional[discord.Embed] = None
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
            embed = cached[1]

        if embed is None:
            embed = await _build_about_embed(guild, interaction.client)
            _CACHE[guild.id] = (time.monotonic(), embed)

        await interaction.followup.send(embed=embed)

    bot.tree.add_command(server_group)
