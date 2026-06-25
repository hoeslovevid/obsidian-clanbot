"""Browse open LFG posts with filters and pagination."""
from __future__ import annotations

import logging
from typing import Optional

import aiosqlite
import discord
from discord import app_commands

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.empty_states import empty_state_embed
from core.reply_helpers import reply_server_only
from core.utils import feature_enabled, feature_off_embed
from core.wf_copy import merge_wf_footer
from database import DB_PATH

logger = logging.getLogger(__name__)

_PER_PAGE = 6


async def _fetch_posts(
    guild_id: int,
    *,
    mission: str | None = None,
    tag: str | None = None,
    open_only: bool = True,
) -> list[tuple]:
    clauses = ["guild_id=?"]
    params: list = [guild_id]
    if open_only:
        clauses.append("status='OPEN'")
    if mission:
        clauses.append("LOWER(mission_type) LIKE ?")
        params.append(f"%{mission.lower()}%")
    if tag:
        clauses.append("LOWER(COALESCE(role_tags,'')) LIKE ?")
        params.append(f"%{tag.lower()}%")
    where = " AND ".join(clauses)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            f"""
            SELECT p.id, p.mission_type, p.max_players, p.creator_id, p.channel_id,
                   p.message_id, p.description, p.role_tags, p.scheduled_at,
                   (SELECT COUNT(*) FROM lfg_rsvps r WHERE r.lfg_id=p.id AND r.response='JOIN') AS joined
            FROM lfg_posts p
            WHERE {where}
            ORDER BY p.created_at DESC
            LIMIT 60
            """,
            params,
        )
        return list(await cur.fetchall())


class LFGListView(discord.ui.View):
    def __init__(
        self,
        *,
        posts: list[tuple],
        page: int,
        mission: str | None,
        tag: str | None,
        requester_id: int,
    ):
        super().__init__(timeout=120)
        self.posts = posts
        self.page = page
        self.mission = mission
        self.tag = tag
        self.requester_id = requester_id
        total_pages = max(1, (len(posts) + _PER_PAGE - 1) // _PER_PAGE)
        if page > 0:
            self.add_item(_PageButton("◀ Prev", page - 1, self))
        if page < total_pages - 1:
            self.add_item(_PageButton("Next ▶", page + 1, self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            from core.reply_helpers import reply_error
            await reply_error(interaction, "Not for you", "Run `/lfg list` yourself to browse.")
            return False
        return True


class _PageButton(discord.ui.Button):
    def __init__(self, label: str, page: int, parent: LFGListView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._page = page
        self._parent = parent

    async def callback(self, interaction: discord.Interaction):
        embed, view = _build_page(
            interaction.guild,
            self._parent.posts,
            page=self._page,
            mission=self._parent.mission,
            tag=self._parent.tag,
            requester_id=self._parent.requester_id,
            client=interaction.client,
        )
        await interaction.response.edit_message(embed=embed, view=view)


def _build_page(
    guild: discord.Guild,
    posts: list[tuple],
    *,
    page: int,
    mission: str | None,
    tag: str | None,
    requester_id: int,
    client,
) -> tuple[discord.Embed, LFGListView]:
    start = page * _PER_PAGE
    chunk = posts[start : start + _PER_PAGE]
    total_pages = max(1, (len(posts) + _PER_PAGE - 1) // _PER_PAGE)
    lines = []
    for row in chunk:
        lfg_id, mission_type, max_p, creator_id, ch_id, msg_id, desc, tags, sched, joined = row
        creator = guild.get_member(creator_id)
        host = creator.display_name if creator else f"User {creator_id}"
        slots = f"{joined}/{max_p}"
        full = joined >= max_p
        status = "🔴 Full" if full else f"🟢 {max_p - joined} open"
        jump = ""
        if ch_id and msg_id:
            jump = f" · [Jump](https://discord.com/channels/{guild.id}/{ch_id}/{msg_id})"
        line = f"**#{lfg_id}** · {mission_type} · {slots} · {status}{jump}\n-# Host: {host}"
        if tags:
            line += f" · Tags: {tags[:60]}"
        if sched:
            line += f" · 🕐 {sched[:40]}"
        if desc:
            line += f"\n-# {str(desc)[:80]}"
        lines.append(line)

    filters = []
    if mission:
        filters.append(f"mission `{mission}`")
    if tag:
        filters.append(f"tag `{tag}`")
    filter_note = f"\n-# Filters: {', '.join(filters)}" if filters else ""

    footer = merge_wf_footer(
        f"{footer_for('community_lfg')} · {len(posts)} open · page {page + 1}/{total_pages}",
        "warframe:lfg_list",
    )
    embed = embed_template(
        "showcase",
        "🤝 Open LFG posts",
        ("\n\n".join(lines) if lines else "_No posts on this page._") + filter_note,
        category="community",
        footer=footer,
        client=client,
        guild_id=guild.id,
    )
    view = LFGListView(
        posts=posts,
        page=page,
        mission=mission,
        tag=tag,
        requester_id=requester_id,
    )
    return embed, view


def setup(bot, group=None):
    command_decorator = (
        group.command(name="list", description="Browse open LFG posts (filter by mission or role tags).")
        if group
        else bot.tree.command(name="lfg_list", description="Browse open LFG posts.")
    )

    @command_decorator
    @app_commands.describe(
        mission="Filter by mission name (partial match)",
        tag="Filter by role tag (Steel Path, Support, etc.)",
        include_full="Include full groups (default: open slots only)",
    )
    async def lfg_list_cmd(
        interaction: discord.Interaction,
        mission: Optional[str] = None,
        tag: Optional[str] = None,
        include_full: bool = False,
    ):
        if not interaction.guild:
            return await reply_server_only(interaction)
        if not await feature_enabled(interaction.guild.id, "lfg"):
            return await interaction.response.send_message(
                embed=feature_off_embed("LFG", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        posts = await _fetch_posts(
            interaction.guild.id,
            mission=(mission or "").strip() or None,
            tag=(tag or "").strip() or None,
            open_only=not include_full,
        )
        if not include_full:
            posts = [p for p in posts if p[9] < p[2]]  # joined < max_players

        if not posts:
            from core.lfg_list import LFGListEmptyView

            return await interaction.followup.send(
                embed=empty_state_embed(
                    "🤝 No open LFG posts",
                    "Nobody is recruiting right now.",
                    action_hint="Post your own with `/lfg` or pick a template below.",
                    category="community",
                    client=interaction.client,
                ),
                view=LFGListEmptyView(interaction.client),
                ephemeral=True,
            )

        embed, view = _build_page(
            interaction.guild,
            posts,
            page=0,
            mission=mission,
            tag=tag,
            requester_id=interaction.user.id,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
