"""/vc commands: host transfer, presets, and idle-VC revival vote.

Covers items 44 (host hand-off), 45 (presets), and 47 (revival vote).

NOTE: this module owns three small SQLite tables that we create lazily so we
don't have to touch ``database/schema.py``:
    * ``vc_presets``       — per-user saved VC configurations
    * ``vc_revivals``      — pending revival votes for closed temp-VCs
    * ``vc_revival_votes`` — distinct clicker tracking for vc_revivals
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import (
    obsidian_embed,
    success_embed,
    error_embed,
    is_mod,
    EMBED_COLORS,
    AUTOCOMPLETE_MAX_CHOICES,
    channel_jump_url,
)
from database import DB_PATH, get_guild_setting, set_guild_setting
from core.vc_permissions import (
    GUILD_VC_STAFF_SETTING,
    apply_staff_overwrites_to_mapping,
    can_manage_temp_vc,
    env_mod_role_names,
    get_vc_staff_roles,
)

logger = logging.getLogger(__name__)


VC_REVIVAL_VOTES = max(1, int(os.getenv("VC_REVIVAL_VOTES", "3")))
VC_REVIVAL_TTL_MINUTES = max(1, int(os.getenv("VC_REVIVAL_TTL_MINUTES", "10")))


# -------------------- table helpers --------------------

_TABLES_READY = False


async def _ensure_tables() -> None:
    """Create tables if missing. Idempotent and called by every public entry."""
    global _TABLES_READY
    if _TABLES_READY:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS vc_presets (
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                vc_name TEXT NOT NULL,
                user_limit INTEGER NOT NULL DEFAULT 0,
                locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, name)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS vc_revivals (
                token TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER,
                message_id INTEGER,
                vc_name TEXT NOT NULL,
                user_limit INTEGER NOT NULL DEFAULT 0,
                host_id INTEGER NOT NULL,
                category_id INTEGER,
                expires_at TEXT NOT NULL,
                votes INTEGER NOT NULL DEFAULT 0,
                resolved INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS vc_revival_votes (
                token TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                voted_at TEXT NOT NULL,
                PRIMARY KEY (token, user_id)
            )
            """
        )
        await db.commit()
    _TABLES_READY = True


async def _get_vc_owner(guild_id: int, channel_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else None


async def _set_vc_owner(guild_id: int, channel_id: int, new_owner_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE temp_vcs SET owner_id=? WHERE guild_id=? AND channel_id=?",
            (new_owner_id, guild_id, channel_id),
        )
        await db.commit()


def _user_voice_channel(member: discord.Member) -> Optional[discord.VoiceChannel]:
    vs = member.voice
    return vs.channel if vs and isinstance(vs.channel, discord.VoiceChannel) else None


# -------------------- HOST TRANSFER (Item 44) --------------------


async def _do_transfer(
    interaction: discord.Interaction,
    vc: discord.VoiceChannel,
    new_owner: discord.Member,
) -> None:
    """Re-permission ``vc`` so ``new_owner`` becomes the host. Caller validates."""
    overwrites = dict(vc.overwrites)
    old_owner_id = await _get_vc_owner(interaction.guild.id, vc.id)
    old_owner = interaction.guild.get_member(old_owner_id) if old_owner_id else None
    if old_owner:
        ow = overwrites.get(old_owner, discord.PermissionOverwrite())
        ow.manage_channels = False
        ow.move_members = False
        ow.mute_members = False
        ow.deafen_members = False
        overwrites[old_owner] = ow
    new_ow = overwrites.get(new_owner, discord.PermissionOverwrite())
    new_ow.view_channel = True
    new_ow.connect = True
    new_ow.manage_channels = True
    new_ow.move_members = True
    new_ow.mute_members = True
    new_ow.deafen_members = True
    overwrites[new_owner] = new_ow
    staff_roles = await get_vc_staff_roles(interaction.guild)
    overwrites = apply_staff_overwrites_to_mapping(overwrites, staff_roles)
    await vc.edit(overwrites=overwrites, reason="VC host transfer")
    await _set_vc_owner(interaction.guild.id, vc.id, new_owner.id)

    try:
        from core.music_player import transfer_dj_control

        await transfer_dj_control(interaction.guild.id, new_owner.id)
    except Exception as e:
        logger.debug(f"[vc] music DJ transfer failed: {e}")

    try:
        await new_owner.send(
            embed=success_embed(
                "You're the new VC host",
                f"You now control **{vc.name}** in **{interaction.guild.name}**.",
                client=interaction.client,
            )
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


# -------------------- PRESETS (Item 45) --------------------


async def _list_presets(user_id: int) -> list[tuple[str, str, int, int]]:
    await _ensure_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name, vc_name, user_limit, locked FROM vc_presets WHERE user_id=? ORDER BY name",
            (user_id,),
        )
        return [(str(n), str(vn), int(ul), int(lk)) for n, vn, ul, lk in await cur.fetchall()]


async def _save_preset(user_id: int, name: str, vc_name: str, user_limit: int, locked: bool) -> None:
    await _ensure_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO vc_presets(user_id, name, vc_name, user_limit, locked, created_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id, name) DO UPDATE SET
                vc_name=excluded.vc_name,
                user_limit=excluded.user_limit,
                locked=excluded.locked
            """,
            (user_id, name, vc_name, user_limit, 1 if locked else 0, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def _get_preset(user_id: int, name: str) -> Optional[tuple[str, int, int]]:
    await _ensure_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT vc_name, user_limit, locked FROM vc_presets WHERE user_id=? AND name=?",
            (user_id, name),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return (str(row[0]), int(row[1]), int(row[2]))


async def _delete_preset(user_id: int, name: str) -> bool:
    await _ensure_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM vc_presets WHERE user_id=? AND name=?",
            (user_id, name),
        )
        await db.commit()
        return (cur.rowcount or 0) > 0


async def apply_preset_to_vc(
    vc: discord.VoiceChannel,
    preset: tuple[str, int, int],
) -> None:
    """Apply ``preset`` (vc_name, user_limit, locked) to the live ``vc``."""
    vc_name, user_limit, locked_int = preset
    overwrites = vc.overwrites
    everyone = vc.guild.default_role
    ow = overwrites.get(everyone, discord.PermissionOverwrite())
    ow.connect = not bool(locked_int)
    overwrites[everyone] = ow
    await vc.edit(
        name=vc_name[:90],
        user_limit=max(0, min(99, user_limit)),
        overwrites=overwrites,
        reason="Apply VC preset",
    )


async def maybe_apply_pending_preset(member: discord.Member, vc: discord.VoiceChannel) -> bool:
    """Called from the join-to-create flow. Consumes ``vc_next_preset:{user_id}`` if set."""
    pending = await get_guild_setting(member.guild.id, f"vc_next_preset:{member.id}")
    if not pending:
        return False
    preset = await _get_preset(member.id, pending)
    await set_guild_setting(member.guild.id, f"vc_next_preset:{member.id}", "")
    if not preset:
        return False
    try:
        await apply_preset_to_vc(vc, preset)
        return True
    except Exception as e:
        logger.debug(f"[vc] maybe_apply_pending_preset failed: {e}")
        return False


# -------------------- REVIVAL VOTE (Item 47) --------------------


class RevivalView(discord.ui.View):
    """Persistent: ``custom_id=vc_revival:{token}``."""

    def __init__(self, token: Optional[str] = None):
        super().__init__(timeout=None)
        self.token = token
        btn = discord.ui.Button(
            label="Revive VC",
            emoji="🔁",
            style=discord.ButtonStyle.primary,
            custom_id=f"vc_revival:{token}" if token else "vc_revival:placeholder",
        )
        btn.callback = self._on_click
        self.add_item(btn)

    async def _on_click(self, interaction: discord.Interaction):
        # Resolve token from the actual custom_id, since persistent views are
        # rebuilt on startup without state.
        component_id = (interaction.data or {}).get("custom_id") or ""
        if not component_id.startswith("vc_revival:"):
            return await interaction.response.send_message("Bad button.", ephemeral=True)
        token = component_id.split(":", 1)[1]
        await _handle_revival_click(interaction, token)


async def _record_revival_intent(
    guild: discord.Guild,
    vc: discord.VoiceChannel,
    *,
    log_channel: discord.TextChannel,
) -> None:
    """Public hook called by the cleanup task right before it deletes ``vc``.

    Captures metadata, posts the revival-vote message, and stores everything
    in the ``vc_revivals`` table.
    """
    await _ensure_tables()
    owner_id = await _get_vc_owner(guild.id, vc.id) or 0
    token = secrets.token_hex(4)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=VC_REVIVAL_TTL_MINUTES)

    embed = obsidian_embed(
        "🌙 VC closed",
        (
            f"**{vc.name}** was idle and is being closed.\n"
            f"Click below within **{VC_REVIVAL_TTL_MINUTES} min** to bring it back. "
            f"It revives once **{VC_REVIVAL_VOTES} distinct clicks** are reached."
        ),
        category="community",
        footer=f"Revival vote • Token {token}",
        client=guild.me._state._get_client() if hasattr(guild.me, "_state") else None,
    )
    view = RevivalView(token=token)
    try:
        msg = await log_channel.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.debug(f"[vc-revival] could not post revival message: {e}")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO vc_revivals
                (token, guild_id, channel_id, message_id, vc_name, user_limit,
                 host_id, category_id, expires_at, votes, resolved)
            VALUES (?,?,?,?,?,?,?,?,?,0,0)
            """,
            (
                token,
                guild.id,
                log_channel.id,
                msg.id,
                vc.name,
                int(vc.user_limit or 0),
                int(owner_id),
                int(vc.category.id) if vc.category else None,
                expires_at.isoformat(),
            ),
        )
        await db.commit()


async def _handle_revival_click(interaction: discord.Interaction, token: str) -> None:
    await _ensure_tables()
    if not interaction.guild:
        return await interaction.response.send_message("Use this in a server.", ephemeral=True)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT guild_id, channel_id, message_id, vc_name, user_limit, host_id, "
            "category_id, expires_at, votes, resolved FROM vc_revivals WHERE token=?",
            (token,),
        )
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message(
            "This revival vote no longer exists.", ephemeral=True
        )
    (
        gid, ch_id, msg_id, vc_name, user_limit, host_id,
        cat_id, expires_at, votes, resolved
    ) = row
    if int(gid) != interaction.guild.id:
        return await interaction.response.send_message("Wrong server.", ephemeral=True)
    if int(resolved):
        return await interaction.response.send_message(
            "This revival vote is already closed.", ephemeral=True
        )

    try:
        expiry = datetime.fromisoformat(str(expires_at))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except Exception:
        expiry = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) >= expiry:
        return await interaction.response.send_message(
            "This vote has expired.", ephemeral=True
        )

    # Record this user's vote (idempotent).
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO vc_revival_votes(token, user_id, voted_at) VALUES(?,?,?)",
            (token, interaction.user.id, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
        added = (cur.rowcount or 0) > 0
        if added:
            await db.execute(
                "UPDATE vc_revivals SET votes=votes+1 WHERE token=?",
                (token,),
            )
            await db.commit()
        cur = await db.execute(
            "SELECT votes FROM vc_revivals WHERE token=?",
            (token,),
        )
        votes_row = await cur.fetchone()
        current_votes = int(votes_row[0]) if votes_row else int(votes)

    if not added:
        return await interaction.response.send_message(
            f"You already voted. Total: **{current_votes}/{VC_REVIVAL_VOTES}**.", ephemeral=True
        )

    if current_votes < VC_REVIVAL_VOTES:
        try:
            await interaction.response.send_message(
                f"Vote counted. **{current_votes}/{VC_REVIVAL_VOTES}** clicks.", ephemeral=True
            )
        except discord.HTTPException:
            pass
        return

    # Threshold reached — revive the VC.
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    category = guild.get_channel(int(cat_id)) if cat_id else None
    if not isinstance(category, discord.CategoryChannel):
        category = None
    try:
        new_vc = await guild.create_voice_channel(
            name=str(vc_name)[:90],
            user_limit=int(user_limit or 0),
            category=category,
            reason="VC revival vote reached threshold",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            embed=error_embed("Can't recreate VC", "I lack permission.", client=interaction.client),
            ephemeral=True,
        )

    # Restore host_id in temp_vcs so the panel still works.
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO temp_vcs(guild_id, channel_id, owner_id, created_at, last_nonempty_at) "
                "VALUES(?,?,?,?,?)",
                (
                    guild.id, new_vc.id, int(host_id) or interaction.user.id,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.execute(
                "UPDATE vc_revivals SET resolved=1 WHERE token=?",
                (token,),
            )
            await db.commit()
    except Exception as e:
        logger.debug(f"[vc-revival] db write failed after recreation: {e}")

    # Edit the original message to show success.
    try:
        ch = guild.get_channel(int(ch_id))
        if isinstance(ch, discord.TextChannel):
            msg = await ch.fetch_message(int(msg_id))
            new_embed = obsidian_embed(
                "✅ VC revived",
                f"**{vc_name}** is back: <#{new_vc.id}>\n[Jump here]({channel_jump_url(guild.id, new_vc.id)})",
                category="success",
                client=interaction.client,
            )
            view = discord.ui.View()
            await msg.edit(embed=new_embed, view=view)
    except Exception:
        pass

    await interaction.followup.send(
        embed=success_embed("VC revived!", f"<#{new_vc.id}> is ready.", client=interaction.client),
        ephemeral=True,
    )


async def expire_pending_revivals(bot: discord.Client) -> None:
    """Called periodically to clean up expired revival messages."""
    await _ensure_tables()
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT token, guild_id, channel_id, message_id FROM vc_revivals "
            "WHERE resolved=0 AND expires_at < ?",
            (now_iso,),
        )
        rows = await cur.fetchall()
        if not rows:
            return
        for token, gid, ch_id, msg_id in rows:
            await db.execute("UPDATE vc_revivals SET resolved=1 WHERE token=?", (token,))
        await db.commit()
    for token, gid, ch_id, msg_id in rows:
        try:
            guild = bot.get_guild(int(gid))
            if not guild:
                continue
            ch = guild.get_channel(int(ch_id))
            if not isinstance(ch, discord.TextChannel):
                continue
            msg = await ch.fetch_message(int(msg_id))
            old_embed = msg.embeds[0] if msg.embeds else None
            if old_embed:
                old_embed.set_footer(text=(old_embed.footer.text or "") + " • (vote expired)")
            new_view = discord.ui.View()
            await msg.edit(embed=old_embed, view=new_view)
        except Exception:
            continue


# -------------------- SLASH COMMANDS --------------------


async def _preset_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    presets = await _list_presets(interaction.user.id)
    cur_lower = (current or "").lower()
    out: list[app_commands.Choice[str]] = []
    for name, _vc_name, _ul, _lk in presets:
        if not cur_lower or cur_lower in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=name[:100]))
        if len(out) >= AUTOCOMPLETE_MAX_CHOICES:
            break
    return out


def setup(bot, group=None):
    """Register the /vc command group. Always creates its own subgroup."""

    vc_group = group  # passed-in group is the dedicated `vc` group from commands_loader

    if vc_group is None:
        logger.warning("[vc] No group passed to vc.setup(); skipping registration")
        return

    # /vc transfer ----------------------------------------------------------------
    @vc_group.command(name="transfer", description="Hand off VC ownership to another member in your VC.")
    @app_commands.describe(to="New host (must currently be in your VC)")
    async def vc_transfer(interaction: discord.Interaction, to: discord.Member):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if to.bot:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Target", "Pick a non-bot member.", client=interaction.client),
                ephemeral=True,
            )
        caller_vc = _user_voice_channel(interaction.user)
        if not caller_vc:
            return await interaction.response.send_message(
                embed=error_embed("Not in a VC", "Join your temp VC first.", client=interaction.client),
                ephemeral=True,
            )
        owner_id = await _get_vc_owner(interaction.guild.id, caller_vc.id)
        if owner_id is None:
            return await interaction.response.send_message(
                embed=error_embed("Not a temp VC", "This isn't a managed temp VC.", client=interaction.client),
                ephemeral=True,
            )
        if not await can_manage_temp_vc(interaction.user, interaction.guild, owner_id=owner_id):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only the current host or staff can transfer.", client=interaction.client),
                ephemeral=True,
            )
        if to.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=error_embed("Same user", "You're already the host.", client=interaction.client),
                ephemeral=True,
            )
        target_vc = _user_voice_channel(to)
        if target_vc is None or target_vc.id != caller_vc.id:
            return await interaction.response.send_message(
                embed=error_embed("Target not in your VC", f"{to.mention} must currently be in {caller_vc.mention}.", client=interaction.client),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        try:
            await _do_transfer(interaction, caller_vc, to)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=error_embed("Permission Denied", "I lack channel-edit permission.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.followup.send(
            embed=success_embed(
                "VC host transferred",
                f"{to.mention} now controls {caller_vc.mention}.",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # /vc save_preset -------------------------------------------------------------
    @vc_group.command(name="save_preset", description="Save your current VC config (name/limit/locked) as a preset.")
    @app_commands.describe(name="Preset name, e.g. 'ESO'")
    async def vc_save_preset(interaction: discord.Interaction, name: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        name = name.strip()
        if not (1 <= len(name) <= 32):
            return await interaction.response.send_message(
                embed=error_embed("Bad name", "Preset name must be 1–32 chars.", client=interaction.client),
                ephemeral=True,
            )
        vc = _user_voice_channel(interaction.user)
        if not vc:
            return await interaction.response.send_message(
                embed=error_embed("Not in a VC", "Join a temp VC first.", client=interaction.client),
                ephemeral=True,
            )
        owner_id = await _get_vc_owner(interaction.guild.id, vc.id)
        if not await can_manage_temp_vc(interaction.user, interaction.guild, owner_id=owner_id):
            return await interaction.response.send_message(
                embed=error_embed("Not your VC", "Only the host or staff can save its config as a preset.", client=interaction.client),
                ephemeral=True,
            )
        everyone_ow = vc.overwrites_for(interaction.guild.default_role)
        locked = bool(everyone_ow.connect is False)
        await _save_preset(interaction.user.id, name, vc.name, int(vc.user_limit or 0), locked)
        await interaction.response.send_message(
            embed=success_embed(
                "Preset saved",
                f"`{name}` → **{vc.name}** • limit={vc.user_limit or 0} • locked={'yes' if locked else 'no'}",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # /vc apply -------------------------------------------------------------------
    @vc_group.command(name="apply", description="Apply a saved VC preset to your current VC (or queue for next).")
    @app_commands.describe(name="Preset name to apply")
    @app_commands.autocomplete(name=_preset_name_autocomplete)
    async def vc_apply(interaction: discord.Interaction, name: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        preset = await _get_preset(interaction.user.id, name)
        if not preset:
            return await interaction.response.send_message(
                embed=error_embed("Preset not found", f"You have no preset named `{name[:30]}`.", client=interaction.client),
                ephemeral=True,
            )
        vc = _user_voice_channel(interaction.user)
        if vc is None:
            await set_guild_setting(interaction.guild.id, f"vc_next_preset:{interaction.user.id}", name)
            return await interaction.response.send_message(
                embed=success_embed(
                    "Preset queued",
                    f"`{name}` will be applied to your next created VC.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        owner_id = await _get_vc_owner(interaction.guild.id, vc.id)
        if not await can_manage_temp_vc(interaction.user, interaction.guild, owner_id=owner_id):
            return await interaction.response.send_message(
                embed=error_embed("Not your VC", "Only the host or staff can apply a preset to a VC.", client=interaction.client),
                ephemeral=True,
            )
        try:
            await apply_preset_to_vc(vc, preset)
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=error_embed("Can't edit channel", "I lack the channel-edit permission.", client=interaction.client),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            from core.utils import channel_name_edit_error

            friendly = channel_name_edit_error(exc)
            if friendly:
                return await interaction.response.send_message(
                    embed=error_embed(
                        "Preset name blocked",
                        friendly,
                        action_hint="Edit the preset name and try again.",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            raise
        await interaction.response.send_message(
            embed=success_embed("Preset applied", f"`{name}` applied to {vc.mention}.", client=interaction.client),
            ephemeral=True,
        )

    # /vc presets -----------------------------------------------------------------
    @vc_group.command(name="presets", description="List your saved VC presets.")
    async def vc_presets(interaction: discord.Interaction):
        presets = await _list_presets(interaction.user.id)
        if not presets:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "🎛️ Your VC presets",
                    "You have no presets yet. Save one with `/vc save_preset`.",
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = []
        for name, vc_name, ul, lk in presets[:25]:
            lines.append(
                f"• `{name}` → **{vc_name}** • limit={ul} • locked={'yes' if lk else 'no'}"
            )
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🎛️ Your VC presets",
                "\n".join(lines),
                category="general",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # /vc delete_preset -----------------------------------------------------------
    @vc_group.command(name="delete_preset", description="Delete a saved VC preset.")
    @app_commands.describe(name="Preset name to delete")
    @app_commands.autocomplete(name=_preset_name_autocomplete)
    async def vc_delete_preset(interaction: discord.Interaction, name: str):
        ok = await _delete_preset(interaction.user.id, name)
        if not ok:
            return await interaction.response.send_message(
                embed=error_embed("Preset not found", f"You have no preset named `{name[:30]}`.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed("Preset deleted", f"`{name}` removed.", client=interaction.client),
            ephemeral=True,
        )

    # /vc staff_roles -------------------------------------------------------------
    @vc_group.command(
        name="staff_roles",
        description="Configure roles that can manage temp VCs and use the panel (admin only).",
    )
    @app_commands.describe(
        action="list, add, remove, or clear",
        role="Role to add or remove (not needed for list/clear)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="Clear", value="clear"),
    ])
    async def vc_staff_roles(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        role: Optional[discord.Role] = None,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only administrators can configure VC staff roles.", client=interaction.client),
                ephemeral=True,
            )

        saved = await get_guild_setting(interaction.guild.id, GUILD_VC_STAFF_SETTING) or ""
        role_ids = [int(x) for x in saved.split(",") if x.strip().isdigit()]
        act = action.value

        if act == "list":
            guild_roles = [interaction.guild.get_role(rid) for rid in role_ids]
            guild_lines = [
                f"• {r.mention}" for r in guild_roles if r is not None
            ] or ["_(none configured in this server)_"]
            env_names = env_mod_role_names()
            env_lines = [f"• `{name}` (env)" for name in env_names] if env_names else ["_(none)_"]
            effective = await get_vc_staff_roles(interaction.guild)
            effective_lines = [f"• {r.mention}" for r in effective] or ["_(fallback admin role only)_"]
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "🛡️ Temp VC staff roles",
                    "**This server**\n" + "\n".join(guild_lines)
                    + "\n\n**From env (`MOD_ROLE_NAME` / `MOD_ROLE_NAMES`)**\n"
                    + "\n".join(env_lines)
                    + "\n\n**Effective (used on new VCs + panel)**\n"
                    + "\n".join(effective_lines),
                    category="general",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if act == "clear":
            await set_guild_setting(interaction.guild.id, GUILD_VC_STAFF_SETTING, "")
            return await interaction.response.send_message(
                embed=success_embed(
                    "Staff roles cleared",
                    "Server-specific VC staff roles removed. Env roles still apply if set.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if role is None:
            return await interaction.response.send_message(
                embed=error_embed("Missing role", "Pick a role to add or remove.", client=interaction.client),
                ephemeral=True,
            )

        if act == "add":
            if role.id not in role_ids:
                role_ids.append(role.id)
            await set_guild_setting(interaction.guild.id, GUILD_VC_STAFF_SETTING, ",".join(str(rid) for rid in role_ids))
            return await interaction.response.send_message(
                embed=success_embed(
                    "Staff role added",
                    f"{role.mention} can manage temp VCs and use the panel.\n"
                    "New VCs will copy hub/category permissions and grant this role full VC control.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if act == "remove":
            role_ids = [rid for rid in role_ids if rid != role.id]
            await set_guild_setting(interaction.guild.id, GUILD_VC_STAFF_SETTING, ",".join(str(rid) for rid in role_ids))
            return await interaction.response.send_message(
                embed=success_embed("Staff role removed", f"{role.mention} removed from VC staff roles.", client=interaction.client),
                ephemeral=True,
            )

        return await interaction.response.send_message(
            embed=error_embed("Invalid action", "Use list, add, remove, or clear.", client=interaction.client),
            ephemeral=True,
        )
