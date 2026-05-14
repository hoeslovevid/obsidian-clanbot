"""Helpers for the right-click 'Mod Context' user popup (Item 40).

This module builds a single ephemeral embed showing recent warns, mod notes,
account/economy info, and exposes DM / Warn / Kick / Ban buttons. Each
destructive action goes through a confirmation modal/view.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import discord  # type: ignore
import aiosqlite  # type: ignore

from core.utils import (
    obsidian_embed,
    error_embed,
    success_embed,
    is_mod,
    format_timestamp_readable,
    EMBED_COLORS,
)
from database import DB_PATH, get_guild_setting, get_user_balance, get_user_xp

logger = logging.getLogger(__name__)


async def _fetch_recent_warnings(guild_id: int, user_id: int) -> tuple[int, list[tuple]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        total = (await cur.fetchone() or (0,))[0]
        cur = await db.execute(
            "SELECT moderator_id, reason, created_at FROM warnings "
            "WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 5",
            (guild_id, user_id),
        )
        rows = await cur.fetchall()
    return int(total), list(rows)


async def _fetch_recent_notes(guild_id: int, user_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT moderator_id, note, created_at FROM mod_notes "
            "WHERE guild_id=? AND target_user_id=? ORDER BY created_at DESC LIMIT 5",
            (guild_id, user_id),
        )
        return list(await cur.fetchall())


async def _fetch_reputation(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT reputation_points FROM reputation WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _incident_active(guild_id: int) -> bool:
    enabled = await get_guild_setting(guild_id, "incident_mode_enabled")
    if enabled != "1":
        return False
    until_raw = await get_guild_setting(guild_id, "incident_mode_until_ts")
    try:
        until_ts = int(until_raw or "0")
    except ValueError:
        until_ts = 0
    if until_ts <= 0:
        return True
    return until_ts > int(datetime.now(timezone.utc).timestamp())


def _fmt_dt(s: str) -> str:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return f"<t:{int(dt.timestamp())}:R>"
    except Exception:
        return "—"


async def build_mod_context(interaction: discord.Interaction, member: discord.Member):
    """Return ``(embed, view)`` ready to be sent to the moderator."""
    guild = interaction.guild
    assert guild is not None  # caller guards this

    warn_total, recent_warns = await _fetch_recent_warnings(guild.id, member.id)
    recent_notes = await _fetch_recent_notes(guild.id, member.id)

    try:
        balance = await get_user_balance(guild.id, member.id)
    except Exception:
        balance = 0
    try:
        xp, level, _ = await get_user_xp(guild.id, member.id)
    except Exception:
        xp, level = 0, 0
    rep = await _fetch_reputation(guild.id, member.id)
    incident = await _incident_active(guild.id)

    warn_lines = []
    for mod_id, reason, created_at in recent_warns[:5]:
        warn_lines.append(f"• {_fmt_dt(created_at)} — <@{int(mod_id)}>: {str(reason)[:120]}")
    warn_block = "\n".join(warn_lines) or "_No warnings_"

    note_lines = []
    for mod_id, note, created_at in recent_notes[:5]:
        note_lines.append(f"• {_fmt_dt(created_at)} — <@{int(mod_id)}>: {str(note)[:120]}")
    note_block = "\n".join(note_lines) or "_No notes_"

    account_created = format_timestamp_readable(member.created_at, include_relative=True)
    joined = format_timestamp_readable(member.joined_at, include_relative=True) if member.joined_at else "—"

    summary = (
        f"**Reputation:** {rep:,} • **Coins:** {balance:,} • **Level:** {level} ({xp:,} XP)"
    )
    if incident:
        summary = "🚨 **Incident mode ACTIVE for this server**\n" + summary

    embed = obsidian_embed(
        f"🛡️ Mod Context • {member.display_name}",
        f"{member.mention} (`{member.id}`)\n{summary}",
        category="moderation",
        author=member,
        thumbnail=member.display_avatar.url if member.display_avatar else None,
        fields=[
            ("Account", f"Created: {account_created}", True),
            ("Joined Server", joined, True),
            (f"Warnings ({warn_total})", warn_block, False),
            ("Mod Notes (last 5)", note_block, False),
        ],
        footer="Mod-only view • Actions are confirmed before they fire",
        client=interaction.client,
    )
    view = ModContextView(member, requester_id=interaction.user.id)
    return embed, view


# ----------------------------- Buttons / Modals -----------------------------


class _DMModal(discord.ui.Modal, title="DM this user (mod-signed)"):
    message = discord.ui.TextInput(
        label="Message", style=discord.TextStyle.paragraph, max_length=1500,
        placeholder="Will be sent as a DM. The user sees your name in the footer.",
    )

    def __init__(self, target: discord.Member):
        super().__init__(timeout=300)
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        body = str(self.message.value or "").strip()
        if not body:
            return await interaction.response.send_message(
                embed=error_embed("Empty message", "Please write something to send.", client=interaction.client),
                ephemeral=True,
            )
        dm_embed = obsidian_embed(
            f"📩 Message from {interaction.guild.name} moderators",
            body,
            category="moderation",
            footer=f"From: {interaction.user} • You can reply via /community ticket",
            client=interaction.client,
        )
        try:
            await self.target.send(embed=dm_embed)
            await interaction.response.send_message(
                embed=success_embed("DM sent", f"Message delivered to {self.target.mention}.", client=interaction.client),
                ephemeral=True,
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                embed=error_embed("DM failed", "Couldn't DM that user (DMs disabled or blocked).", client=interaction.client),
                ephemeral=True,
            )


class _KickConfirmModal(discord.ui.Modal, title="Confirm Kick"):
    reason = discord.ui.TextInput(label="Reason", required=False, max_length=400)

    def __init__(self, target: discord.Member):
        super().__init__(timeout=300)
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        reason = str(self.reason.value or "Kicked via Mod Context")
        actor = interaction.user
        if not isinstance(actor, discord.Member) or not is_mod(actor):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "You can't do that.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.response.send_message(
                embed=error_embed("Missing permission", "I don't have **Kick Members**.", client=interaction.client),
                ephemeral=True,
            )
        try:
            await self.target.kick(reason=f"{reason} • by {actor}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=error_embed("Kick failed", "I can't kick that member (role hierarchy).", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed("User kicked", f"{self.target.mention} kicked.\nReason: _{reason}_", client=interaction.client),
            ephemeral=True,
        )


class _BanConfirmModal(discord.ui.Modal, title="Confirm Ban"):
    reason = discord.ui.TextInput(label="Reason", required=False, max_length=400)
    delete_days = discord.ui.TextInput(
        label="Delete recent messages (days, 0–7)",
        required=False, max_length=1, placeholder="0",
    )

    def __init__(self, target: discord.Member):
        super().__init__(timeout=300)
        self.target = target

    async def on_submit(self, interaction: discord.Interaction):
        reason = str(self.reason.value or "Banned via Mod Context")
        try:
            days = int(str(self.delete_days.value or "0").strip())
        except ValueError:
            days = 0
        days = max(0, min(7, days))
        actor = interaction.user
        if not isinstance(actor, discord.Member) or not is_mod(actor):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "You can't do that.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message(
                embed=error_embed("Missing permission", "I don't have **Ban Members**.", client=interaction.client),
                ephemeral=True,
            )
        try:
            await self.target.ban(reason=f"{reason} • by {actor}", delete_message_days=days)
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=error_embed("Ban failed", "I can't ban that member (role hierarchy).", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed(
                "User banned",
                f"{self.target.mention} banned (deleted {days}d of messages).\nReason: _{reason}_",
                client=interaction.client,
            ),
            ephemeral=True,
        )


class ModContextView(discord.ui.View):
    """Ephemeral, 10-minute, mod-only view with DM/Warn/Kick/Ban buttons."""

    def __init__(self, target: discord.Member, *, requester_id: int):
        super().__init__(timeout=600)
        self.target = target
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This Mod Context popup is private to whoever opened it.", ephemeral=True
            )
            return False
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("Mods only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="DM this user", emoji="📩", style=discord.ButtonStyle.primary)
    async def dm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_DMModal(self.target))

    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.secondary)
    async def warn_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from core.modals import WarnUserModal
        await interaction.response.send_modal(WarnUserModal(self.target))

    @discord.ui.button(label="Kick", emoji="🚪", style=discord.ButtonStyle.danger)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_KickConfirmModal(self.target))

    @discord.ui.button(label="Ban", emoji="🔨", style=discord.ButtonStyle.danger)
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_BanConfirmModal(self.target))
