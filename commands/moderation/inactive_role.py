"""Item 83 — auto-tag inactive members with a configurable role.

Mod commands (live under whatever group this module is registered to):
- ``/inactive_role config role:@Inactive days:60``
- ``/inactive_role preview``
- ``/inactive_role clear member:@user``

The background sweep lives in ``tasks/_core.py:inactive_role_sweep_loop``;
on-message and on-voice handlers in ``bot.py`` clear the role automatically
when a tagged member returns. This is purely a visibility role — no kicks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite  # type: ignore
import discord
from discord import app_commands

from core.utils import EMBED_COLORS, error_embed, is_mod, obsidian_embed, success_embed
from database import DB_PATH, delete_guild_setting, get_guild_setting, set_guild_setting

logger = logging.getLogger(__name__)


SETTING_ROLE_ID = "inactive_role_id"
SETTING_THRESHOLD_DAYS = "inactive_threshold_days"
WARN_SENT_PREFIX = "inactive_warn_sent:"
DEFAULT_THRESHOLD_DAYS = 60


def _warn_key(user_id: int) -> str:
    return f"{WARN_SENT_PREFIX}{user_id}"


async def was_inactive_warned(guild_id: int, user_id: int) -> bool:
    return await get_guild_setting(guild_id, _warn_key(user_id)) == "1"


async def mark_inactive_warned(guild_id: int, user_id: int) -> None:
    await set_guild_setting(guild_id, _warn_key(user_id), "1")


async def clear_inactive_warning(guild_id: int, user_id: int) -> None:
    await delete_guild_setting(guild_id, _warn_key(user_id))


async def get_inactive_role_id(guild_id: int) -> Optional[int]:
    raw = await get_guild_setting(guild_id, SETTING_ROLE_ID)
    if raw and str(raw).isdigit():
        return int(raw)
    return None


async def get_inactive_threshold_days(guild_id: int) -> int:
    raw = await get_guild_setting(guild_id, SETTING_THRESHOLD_DAYS)
    if raw and str(raw).isdigit():
        return max(1, int(raw))
    return DEFAULT_THRESHOLD_DAYS


async def _last_activity_for(guild_id: int, user_id: int) -> Optional[datetime]:
    """Return the user's last_activity_date from activity_stats (UTC), or None."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT last_activity_date FROM activity_stats WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
        if not row or not row[0]:
            return None
        return datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except Exception:
        return None


async def list_inactive_members(guild: discord.Guild) -> list[tuple[discord.Member, datetime]]:
    """Return members who would be tagged by the next sweep (best-effort)."""
    threshold = await get_inactive_threshold_days(guild.id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=threshold)

    out: list[tuple[discord.Member, datetime]] = []
    for member in guild.members:
        if member.bot:
            continue
        last = await _last_activity_for(guild.id, member.id)
        if last is None:
            joined = member.joined_at
            if joined is None:
                continue
            ref_dt = joined if joined.tzinfo else joined.replace(tzinfo=timezone.utc)
        else:
            ref_dt = last
        if ref_dt < cutoff:
            out.append((member, ref_dt))
    out.sort(key=lambda t: t[1])
    return out


async def maybe_clear_inactive_role(member: discord.Member) -> None:
    """Hook for on_message / on_voice — strip the inactive role if present."""
    if member.bot or member.guild is None:
        return
    await clear_inactive_warning(member.guild.id, member.id)
    role_id = await get_inactive_role_id(member.guild.id)
    if not role_id:
        return
    role = member.guild.get_role(role_id)
    if role is None or role not in member.roles:
        return
    try:
        await member.remove_roles(role, reason="Inactive role auto-clear: member is active again")
        await clear_inactive_warning(member.guild.id, member.id)
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.debug(f"[inactive_role] could not remove role from {member.id}: {e}")


def setup(bot, group=None):
    """Register `/<group> inactive_role` subgroup. Falls back to top-level
    `/inactive_role` when no parent group is provided."""
    inactive_group = app_commands.Group(name="inactive_role", description="🛌 (mods) Inactive role auto-tagging.")

    @inactive_group.command(name="config", description="(mods) Set the inactive role + threshold (days).")
    @app_commands.describe(
        role="Role to assign to inactive members.",
        days="Days of no activity before tagging (default 60, min 7, max 365).",
    )
    async def config_cmd(interaction: discord.Interaction, role: discord.Role, days: int = DEFAULT_THRESHOLD_DAYS):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        days = max(7, min(365, int(days)))
        me = interaction.guild.me
        if me and role >= me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Role too high",
                    "My top role must be **above** the inactive role for me to add/remove it.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await set_guild_setting(interaction.guild.id, SETTING_ROLE_ID, str(role.id))
        await set_guild_setting(interaction.guild.id, SETTING_THRESHOLD_DAYS, str(days))
        await interaction.response.send_message(
            embed=success_embed(
                "Inactive role configured",
                f"Members with no activity in **{days} days** will be tagged with {role.mention} by the daily sweep.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @inactive_group.command(name="preview", description="(mods) Preview members who'd be tagged inactive right now.")
    async def preview_cmd(interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        role_id = await get_inactive_role_id(interaction.guild.id)
        threshold = await get_inactive_threshold_days(interaction.guild.id)
        rows = await list_inactive_members(interaction.guild)
        role_mention = f"<@&{role_id}>" if role_id else "_(not configured)_"
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🛌 Inactive Preview",
                    f"Threshold: **{threshold} days** · Role: {role_mention}\n\n"
                    "_No members would be tagged right now._",
                    color=EMBED_COLORS["moderation"],
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        body_lines: list[str] = []
        for member, ref in rows[:25]:
            ts = int(ref.timestamp())
            body_lines.append(f"• {member.mention} — last seen <t:{ts}:R>")
        more = "" if len(rows) <= 25 else f"\n_… and {len(rows) - 25} more._"
        await interaction.followup.send(
            embed=obsidian_embed(
                "🛌 Inactive Preview",
                f"Threshold: **{threshold} days** · Role: {role_mention}\n\n" + "\n".join(body_lines) + more,
                color=EMBED_COLORS["moderation"],
                client=interaction.client,
                footer=f"{len(rows)} member(s) match this threshold.",
            ),
            ephemeral=True,
        )

    @inactive_group.command(name="clear", description="(mods) Manually remove the inactive role from a member.")
    @app_commands.describe(member="Member to clear the inactive role from.")
    async def clear_cmd(interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        role_id = await get_inactive_role_id(interaction.guild.id)
        if not role_id:
            return await interaction.response.send_message(
                embed=error_embed("Not configured", "Run `/inactive_role config` first.", client=interaction.client),
                ephemeral=True,
            )
        role = interaction.guild.get_role(role_id)
        if role is None:
            return await interaction.response.send_message(
                embed=error_embed("Role missing", "The configured role was deleted. Reconfigure with `/inactive_role config`.", client=interaction.client),
                ephemeral=True,
            )
        if role not in member.roles:
            return await interaction.response.send_message(
                embed=obsidian_embed("Already clean", f"{member.mention} doesn't currently have {role.mention}.", color=EMBED_COLORS["moderation"], client=interaction.client),
                ephemeral=True,
            )
        try:
            await member.remove_roles(role, reason=f"Inactive role manually cleared by {interaction.user}")
        except (discord.Forbidden, discord.HTTPException) as e:
            return await interaction.response.send_message(
                embed=error_embed("Couldn't remove role", str(e), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed("Role cleared", f"Removed {role.mention} from {member.mention}.", client=interaction.client),
            ephemeral=True,
        )

    # tools_group is currently at the 25-subcommand cap from a previous batch
    # (favorites + phishing already overflow), so this group is always
    # registered as a top-level `/inactive_role` group to avoid evicting them.
    bot.tree.add_command(inactive_group)
