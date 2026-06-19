"""Paginated moderator audit log viewer with filters and export."""
from __future__ import annotations

import csv
import io
from typing import Optional

import aiosqlite
import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.empty_states import empty_state_embed
from core.utils import is_mod
from database import DB_PATH

_PER_PAGE = 8


async def _count_rows(guild_id: int, action_filter: str | None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if action_filter:
            cur = await db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE guild_id=? AND action LIKE ?",
                (guild_id, f"%{action_filter}%"),
            )
        else:
            cur = await db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE guild_id=?",
                (guild_id,),
            )
        return int((await cur.fetchone())[0] or 0)


async def _fetch_audit_rows(
    guild_id: int,
    *,
    limit: int = 8,
    offset: int = 0,
    action_filter: str | None = None,
) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        if action_filter:
            cur = await db.execute(
                """
                SELECT action, actor_id, target_id, target_type, details, created_at
                FROM audit_log
                WHERE guild_id=? AND action LIKE ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (guild_id, f"%{action_filter}%", limit, offset),
            )
        else:
            cur = await db.execute(
                """
                SELECT action, actor_id, target_id, target_type, details, created_at
                FROM audit_log
                WHERE guild_id=?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (guild_id, limit, offset),
            )
        return list(await cur.fetchall())


class AuditLogView(discord.ui.View):
    def __init__(
        self,
        *,
        guild_id: int,
        page: int,
        total_pages: int,
        action_filter: str | None,
        requester_id: int,
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.page = page
        self.total_pages = total_pages
        self.action_filter = action_filter
        self.requester_id = requester_id
        if page > 0:
            self.add_item(_AuditNav("◀ Prev", page - 1, self))
        if page < total_pages - 1:
            self.add_item(_AuditNav("Next ▶", page + 1, self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            from core.reply_helpers import reply_mods_only
            await reply_mods_only(interaction)
            return False
        return True


class _AuditNav(discord.ui.Button):
    def __init__(self, label: str, page: int, parent: AuditLogView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._page = page
        self._parent = parent

    async def callback(self, interaction: discord.Interaction):
        embed, view = await _build_audit_page(
            interaction.guild,
            page=self._page,
            action_filter=self._parent.action_filter,
            requester_id=self._parent.requester_id,
            client=interaction.client,
        )
        await interaction.response.edit_message(embed=embed, view=view)


async def _build_audit_page(
    guild: discord.Guild,
    *,
    page: int,
    action_filter: str | None,
    requester_id: int,
    client,
) -> tuple[discord.Embed, AuditLogView | None]:
    total = await _count_rows(guild.id, action_filter)
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    offset = page * _PER_PAGE
    rows = await _fetch_audit_rows(guild.id, limit=_PER_PAGE, offset=offset, action_filter=action_filter)
    if not rows:
        embed = empty_state_embed(
            "📋 Audit log",
            "No audit entries match this filter.",
            action_hint="Try clearing the action filter or check `/admin logging`.",
            category="moderation",
            client=client,
        )
        return embed, None

    lines = []
    for action, actor_id, target_id, target_type, details, created_at in rows:
        target = f"<@{target_id}>" if target_id and target_type == "user" else (str(target_id) if target_id else "—")
        actor = f"<@{actor_id}>" if actor_id else "system"
        lines.append(
            f"**{action}** · {actor} → {target}\n"
            f"-# {(details or '—')[:80]} · {str(created_at)[:16]}"
        )
    title = "📋 Audit log"
    if action_filter:
        title += f" · `{action_filter}`"
    title += f" · p{page + 1}/{total_pages}"
    embed = embed_template(
        "showcase",
        title,
        "\n\n".join(lines),
        category="moderation",
        footer="Live mirror in audit channel · /admin audit export",
        client=client,
        guild_id=guild.id,
    )
    view = AuditLogView(
        guild_id=guild.id,
        page=page,
        total_pages=total_pages,
        action_filter=action_filter,
        requester_id=requester_id,
    )
    return embed, view


def setup(bot, group=None):
    audit_group = app_commands.Group(name="audit", description="Browse and export the moderator audit log.")
    target = group if group is not None else bot.tree

    @audit_group.command(name="view", description="Browse recent audit log entries (paginated).")
    @app_commands.describe(
        page="Page number (1-based)",
        action="Filter by action substring (e.g. warn, ticket, automod)",
    )
    async def audit_view(
        interaction: discord.Interaction,
        page: app_commands.Range[int, 1, 100] = 1,
        action: Optional[str] = None,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await interaction.response.defer(ephemeral=True)
        action_f = (action or "").strip() or None
        embed, view = await _build_audit_page(
            interaction.guild,
            page=max(0, int(page) - 1),
            action_filter=action_f,
            requester_id=interaction.user.id,
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @audit_group.command(name="export", description="Export audit log as CSV (last 500 entries).")
    @app_commands.describe(action="Optional action filter substring")
    async def audit_export(interaction: discord.Interaction, action: Optional[str] = None):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await interaction.response.defer(ephemeral=True)
        action_f = (action or "").strip() or None
        async with aiosqlite.connect(DB_PATH) as db:
            if action_f:
                cur = await db.execute(
                    """
                    SELECT action, actor_id, target_id, target_type, details, created_at
                    FROM audit_log WHERE guild_id=? AND action LIKE ?
                    ORDER BY id DESC LIMIT 500
                    """,
                    (interaction.guild.id, f"%{action_f}%"),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT action, actor_id, target_id, target_type, details, created_at
                    FROM audit_log WHERE guild_id=? ORDER BY id DESC LIMIT 500
                    """,
                    (interaction.guild.id,),
                )
            rows = await cur.fetchall()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["action", "actor_id", "target_id", "target_type", "details", "created_at"])
        writer.writerows(rows)
        buf.seek(0)
        file = discord.File(io.BytesIO(buf.getvalue().encode("utf-8")), filename="audit_export.csv")
        from core.utils import success_embed

        await interaction.followup.send(
            embed=success_embed(
                "Audit export",
                f"**{len(rows)}** row(s) attached.",
                client=interaction.client,
            ),
            file=file,
            ephemeral=True,
        )

    # Back-compat: /admin audit maps to view
    legacy = (
        group.command(name="audit", description="Browse recent moderator audit log entries.")
        if group
        else bot.tree.command(name="audit", description="Browse recent moderator audit log entries.")
    )

    @legacy
    @app_commands.describe(page="Page number (1-based)", action="Filter by action substring")
    async def audit_cmd(
        interaction: discord.Interaction,
        page: app_commands.Range[int, 1, 100] = 1,
        action: Optional[str] = None,
    ):
        await audit_view(interaction, page=page, action=action)

    if isinstance(target, app_commands.Group):
        target.add_command(audit_group)
    else:
        bot.tree.add_command(audit_group)
