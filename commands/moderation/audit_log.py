"""Paginated moderator audit log viewer."""
from __future__ import annotations

import discord
from discord import app_commands

import aiosqlite

from core.embed_templates import embed_template
from core.utils import is_mod
from database import DB_PATH


async def _fetch_audit_rows(guild_id: int, *, limit: int = 15, offset: int = 0) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
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


def setup(bot, group=None):
    command_decorator = (
        group.command(name="audit", description="Browse recent moderator audit log entries.")
        if group
        else bot.tree.command(name="audit", description="Browse recent moderator audit log entries.")
    )

    @command_decorator
    @app_commands.describe(page="Page number (1-based)")
    async def audit_cmd(interaction: discord.Interaction, page: app_commands.Range[int, 1, 50] = 1):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await interaction.response.defer(ephemeral=True)
        per_page = 10
        offset = (int(page) - 1) * per_page
        rows = await _fetch_audit_rows(interaction.guild.id, limit=per_page, offset=offset)
        if not rows:
            from core.empty_states import empty_state_embed
            return await interaction.followup.send(
                embed=empty_state_embed(
                    "📋 Audit log",
                    "No audit entries yet.",
                    action_hint="Actions like warn, purge, kick, and incident mode appear here.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = []
        for action, actor_id, target_id, target_type, details, created_at in rows:
            target = f"<@{target_id}>" if target_id and target_type == "user" else (str(target_id) if target_id else "—")
            lines.append(
                f"**{action}** · <@{actor_id}> → {target}\n"
                f"-# {(details or '—')[:80]} · {str(created_at)[:16]}"
            )
        embed = embed_template(
            "showcase",
            f"📋 Audit log · page {page}",
            "\n\n".join(lines),
            category="moderation",
            footer="Channel mirror still posts live · /admin logging",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
