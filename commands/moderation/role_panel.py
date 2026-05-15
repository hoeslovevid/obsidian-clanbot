"""/roletools panel_create — self-assignable role button panels (#10).

Creates a persistent embed in the chosen channel with one button per role.
Clicking toggles the role for the user. Panels survive restarts because we
store them in ``role_panels`` and the view is re-registered in
``handlers/startup.py``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore
from discord.ui import Button, View  # type: ignore

from core.utils import obsidian_embed, success_embed, error_embed, is_mod, EMBED_COLORS
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


MAX_PANEL_ROLES = 20  # Discord allows 25 buttons per view, leave room for navigation later.
_ROLE_TOKEN_RE = re.compile(r"<@&(\d+)>|\b(\d{15,22})\b")


# ---------------------------------------------------------------------------
# Persistent view
# ---------------------------------------------------------------------------
class RolePanelButton(Button):
    """Single toggle-role button. ``custom_id`` is bound to the role for persistence."""

    def __init__(self, panel_id: int, role_id: int, label: str, emoji: Optional[str], style: discord.ButtonStyle):
        super().__init__(
            label=label[:80],
            emoji=emoji,
            style=style,
            custom_id=f"rp:{panel_id}:{role_id}",
        )
        self.panel_id = panel_id
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message(
                embed=error_embed("Role missing", "That role no longer exists. Ask a moderator to recreate the panel.", client=interaction.client),
                ephemeral=True,
            )
        # Hierarchy check — bot can't manage roles above its own top role.
        me = interaction.guild.me
        if me is None or role >= me.top_role:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Can't manage that role",
                    f"My highest role isn't above {role.mention}, so I can't toggle it. Ask an admin to fix the role hierarchy.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Role panel self-removal")
                msg = f"Removed {role.mention}."
            else:
                await interaction.user.add_roles(role, reason="Role panel self-add")
                msg = f"Added {role.mention}."
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=error_embed("Permission denied", "I don't have permission to assign that role.", client=interaction.client),
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            logger.debug("[role_panel] role toggle failed: %s", exc)
            return await interaction.response.send_message(
                embed=error_embed("Discord error", "Couldn't update your roles right now. Try again in a moment.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(msg, ephemeral=True)


class RolePanelView(View):
    """Persistent view containing one toggle button per role on the panel."""

    def __init__(self, panel_id: int, roles: list[dict]):
        super().__init__(timeout=None)
        styles = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.danger,
        ]
        for i, r in enumerate(roles[:MAX_PANEL_ROLES]):
            try:
                rid = int(r["role_id"])
            except (KeyError, TypeError, ValueError):
                continue
            label = (r.get("label") or "Role").strip()[:80] or "Role"
            emoji = r.get("emoji") or None
            style = styles[i % len(styles)]
            self.add_item(RolePanelButton(panel_id, rid, label, emoji, style))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def _save_panel(
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    title: str,
    description: str,
    roles: list[dict],
    created_by: int,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO role_panels (guild_id, channel_id, message_id, title, description, roles_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, channel_id, message_id, title, description, json.dumps(roles), created_by, now_utc().isoformat()),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def fetch_all_panels() -> list[dict]:
    """Return all panels (used by handlers/startup to re-register persistent views)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT panel_id, guild_id, channel_id, message_id, title, description, roles_json FROM role_panels"
        )
        rows = await cur.fetchall()
    out = []
    for pid, gid, cid, mid, title, desc, roles_json in rows:
        try:
            roles = json.loads(roles_json) if roles_json else []
        except (ValueError, TypeError):
            roles = []
        out.append({
            "panel_id": int(pid),
            "guild_id": int(gid),
            "channel_id": int(cid),
            "message_id": int(mid),
            "title": title,
            "description": desc,
            "roles": roles,
        })
    return out


# ---------------------------------------------------------------------------
# Setup wizard modal
# ---------------------------------------------------------------------------
class RolePanelModal(discord.ui.Modal, title="Create role panel"):
    panel_title: discord.ui.TextInput
    panel_description: discord.ui.TextInput
    role_lines: discord.ui.TextInput

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel
        self.panel_title = discord.ui.TextInput(
            label="Panel title",
            placeholder="Pick your roles!",
            style=discord.TextStyle.short,
            max_length=120,
            required=True,
        )
        self.panel_description = discord.ui.TextInput(
            label="Description (markdown ok)",
            placeholder="Tap a button below to toggle a role on or off.",
            style=discord.TextStyle.paragraph,
            max_length=900,
            required=False,
        )
        self.role_lines = discord.ui.TextInput(
            label="Roles (one per line: <@&id> [| label] [| emoji])",
            placeholder="<@&123456789012345678> | PC players | 💻\n<@&234...> | PvE | ⚔️",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )
        self.add_item(self.panel_title)
        self.add_item(self.panel_description)
        self.add_item(self.role_lines)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        roles: list[dict] = []
        seen: set[int] = set()
        for raw in (self.role_lines.value or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            head = parts[0]
            label = parts[1] if len(parts) > 1 and parts[1] else None
            emoji = parts[2] if len(parts) > 2 and parts[2] else None
            m = _ROLE_TOKEN_RE.search(head)
            if not m:
                continue
            try:
                rid = int(m.group(1) or m.group(2))
            except (TypeError, ValueError):
                continue
            if rid in seen:
                continue
            role = interaction.guild.get_role(rid)
            if role is None:
                continue
            seen.add(rid)
            roles.append({
                "role_id": rid,
                "label": label or role.name,
                "emoji": emoji,
            })
            if len(roles) >= MAX_PANEL_ROLES:
                break

        if not roles:
            return await interaction.response.send_message(
                embed=error_embed(
                    "No valid roles",
                    "Couldn't parse any role mentions. Use one role per line like `<@&123> | Label | 💻`.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        embed = obsidian_embed(
            self.panel_title.value.strip() or "Pick your roles",
            (self.panel_description.value or "Tap a button below to toggle a role on or off.").strip(),
            color=EMBED_COLORS.get("general"),
            client=interaction.client,
        )
        embed.add_field(
            name="Roles",
            value="\n".join(f"• <@&{r['role_id']}>" for r in roles)[:1024],
            inline=False,
        )

        try:
            view = RolePanelView(panel_id=0, roles=roles)  # placeholder id, replaced after insert
            msg = await self.channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=error_embed("Can't post there", f"I don't have permission to send messages in {self.channel.mention}.", client=interaction.client),
                ephemeral=True,
            )

        panel_id = await _save_panel(
            guild_id=interaction.guild.id,
            channel_id=self.channel.id,
            message_id=msg.id,
            title=self.panel_title.value.strip(),
            description=(self.panel_description.value or "").strip(),
            roles=roles,
            created_by=interaction.user.id,
        )

        # Re-register the view with the real panel_id so custom_ids match exactly.
        try:
            real_view = RolePanelView(panel_id=panel_id, roles=roles)
            await msg.edit(view=real_view)
            interaction.client.add_view(real_view, message_id=msg.id)
        except Exception as exc:
            logger.debug("[role_panel] view rebind failed: %s", exc)

        await interaction.response.send_message(
            embed=success_embed(
                "Role panel posted",
                f"Posted in {self.channel.mention} with **{len(roles)}** role buttons.\nUse `/roletools panel_delete` to take it down.",
                client=interaction.client,
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Slash command setup
# ---------------------------------------------------------------------------
def setup(bot, group=None):
    create_cmd = (
        group.command(name="panel_create", description="Post a button-based self-assignable role panel.")
        if group
        else bot.tree.command(name="panel_create", description="Post a button-based self-assignable role panel.")
    )
    delete_cmd = (
        group.command(name="panel_delete", description="Remove a previously created role panel.")
        if group
        else bot.tree.command(name="panel_delete", description="Remove a previously created role panel.")
    )

    @create_cmd
    @app_commands.describe(channel="Channel where the panel should be posted (defaults to here).")
    async def panel_create(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not (interaction.user.guild_permissions.manage_roles or is_mod(interaction.user)):
            return await interaction.response.send_message(
                embed=error_embed("Permission denied", "Need **Manage Roles** or moderator permission.", client=interaction.client),
                ephemeral=True,
            )
        target = channel
        if target is None and isinstance(interaction.channel, discord.TextChannel):
            target = interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Pick a text channel", "The role panel needs a regular text channel.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_modal(RolePanelModal(target))

    async def _panel_autocomplete(interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT panel_id, title FROM role_panels WHERE guild_id=? ORDER BY panel_id DESC LIMIT 25",
                (interaction.guild.id,),
            )
            rows = await cur.fetchall()
        typed = (current or "").lower()
        out = []
        for pid, title in rows:
            label = f"#{pid} • {title or 'Role panel'}"[:100]
            if not typed or typed in label.lower():
                out.append(app_commands.Choice(name=label, value=int(pid)))
        return out[:25]

    @delete_cmd
    @app_commands.describe(panel_id="Panel to remove (autocomplete shows recent panels).")
    @app_commands.autocomplete(panel_id=_panel_autocomplete)
    async def panel_delete(interaction: discord.Interaction, panel_id: int):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not (interaction.user.guild_permissions.manage_roles or is_mod(interaction.user)):
            return await interaction.response.send_message(
                embed=error_embed("Permission denied", "Need **Manage Roles** or moderator permission.", client=interaction.client),
                ephemeral=True,
            )

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, message_id FROM role_panels WHERE guild_id=? AND panel_id=?",
                (interaction.guild.id, panel_id),
            )
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message(
                    embed=error_embed("Not found", "No role panel with that id.", client=interaction.client),
                    ephemeral=True,
                )
            cid, mid = int(row[0]), int(row[1])
            await db.execute(
                "DELETE FROM role_panels WHERE guild_id=? AND panel_id=?",
                (interaction.guild.id, panel_id),
            )
            await db.commit()

        # Best-effort delete the actual message.
        ch = interaction.guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(mid)
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await interaction.response.send_message(
            embed=success_embed("Panel removed", f"Role panel `#{panel_id}` deleted.", client=interaction.client),
            ephemeral=True,
        )
