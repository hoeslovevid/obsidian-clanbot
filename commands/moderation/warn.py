"""Warn system commands."""
import discord
from discord import app_commands
from typing import Optional
import dateparser

from core.embed_footers import footer_for
from core.embed_templates import embed_template
from core.utils import obsidian_embed, success_embed, error_embed, is_mod, channel_jump_url, copy_friendly_id, format_number, pluralize, EMBED_COLORS, AUTOCOMPLETE_MAX_CHOICES
from database import DB_PATH, now_utc, get_log_channel_id
from views import EmbedPaginator
import aiosqlite


# Item 38: saved warn reason templates. Created lazily — schema.py untouched.
_TEMPLATES_READY = False


async def _ensure_template_table() -> None:
    global _TEMPLATES_READY
    if _TEMPLATES_READY:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS warn_reason_templates (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                template TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                PRIMARY KEY (guild_id, name)
            )
            """
        )
        await db.commit()
    _TEMPLATES_READY = True


async def _list_templates(guild_id: int) -> list[tuple[str, str]]:
    await _ensure_template_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name, template FROM warn_reason_templates WHERE guild_id=? ORDER BY name",
            (guild_id,),
        )
        return [(str(n), str(t)) for n, t in await cur.fetchall()]


async def _get_template(guild_id: int, name: str) -> Optional[str]:
    await _ensure_template_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT template FROM warn_reason_templates WHERE guild_id=? AND name=?",
            (guild_id, name),
        )
        row = await cur.fetchone()
    return str(row[0]) if row else None


async def execute_warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Execute warn logic (called from slash command or context menu)."""
    if not interaction.guild:
        return await interaction.response.send_message(
            embed=error_embed("Invalid Context", "This can only be used in a server.", client=interaction.client),
            ephemeral=True,
        )
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        return await interaction.response.send_message(
            embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
            ephemeral=True,
        )
    if user.bot:
        return await interaction.response.send_message(
            embed=error_embed("Invalid User", "You cannot warn bots.", client=interaction.client),
            ephemeral=True,
        )

    if not interaction.response.is_done():
        await interaction.response.defer()

    case_id = None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (interaction.guild.id, user.id, interaction.user.id, reason, now_utc().isoformat()))
        case_id = cur.lastrowid
        await db.commit()

        cur = await db.execute("""
            SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?
        """, (interaction.guild.id, user.id))
        warning_count = (await cur.fetchone())[0]

        cur = await db.execute("""
            SELECT max_warnings, action_after_max FROM warn_settings WHERE guild_id=?
        """, (interaction.guild.id,))
        settings_row = await cur.fetchone()
        max_warnings = settings_row[0] if settings_row else 3
        action = settings_row[1] if settings_row else "mute"

    try:
        from core.audit import log_audit
        bot_ref = getattr(interaction.client, "bot", interaction.client)
        await log_audit(
            interaction.guild.id,
            "warn",
            interaction.user.id,
            target_id=user.id,
            target_type="user",
            details=(reason or "")[:200],
            bot=bot_ref,
        )
    except Exception:
        pass

    if warning_count >= max_warnings:
        if action == "mute":
            mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
            if not mute_role:
                try:
                    mute_role = await interaction.guild.create_role(name="Muted", reason="Auto-created for warn system")
                    for channel in interaction.guild.channels:
                        try:
                            await channel.set_permissions(mute_role, send_messages=False, speak=False)
                        except Exception:
                            pass
                except discord.Forbidden:
                    pass
            if mute_role:
                try:
                    await user.add_roles(mute_role, reason=f"Auto-muted after {warning_count} warnings")
                except discord.Forbidden:
                    pass
        elif action == "kick":
            try:
                await user.kick(reason=f"Auto-kicked after {warning_count} warnings")
            except discord.Forbidden:
                pass
        elif action == "ban":
            try:
                await user.ban(reason=f"Auto-banned after {warning_count} warnings", delete_message_days=0)
            except discord.Forbidden:
                pass

    try:
        dm_embed = obsidian_embed(
            f"⚠️ Warning in {interaction.guild.name}",
            f"**Reason:** {reason}\n**Warnings:** {warning_count}/{max_warnings}\n\n"
            f"{'⚠️ You have reached the maximum warnings!' if warning_count >= max_warnings else 'Please follow the server rules.'}",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        await user.send(embed=dm_embed)
    except Exception:
        pass

    try:
        from core.audit import log_audit
        bot_ref = getattr(interaction.client, "bot", interaction.client) or interaction.client
        await log_audit(interaction.guild.id, "warn", interaction.user.id, target_id=user.id, target_type="user", details=reason[:200], bot=bot_ref)
    except Exception:
        pass

    log_channel_id = await get_log_channel_id(interaction.guild.id, "member_warn")
    if log_channel_id and interaction.channel:
        log_channel = interaction.guild.get_channel(log_channel_id)
        if log_channel and isinstance(log_channel, discord.TextChannel):
            jump_url = channel_jump_url(interaction.guild.id, interaction.channel.id)
            case_ref = f"**Case #** {case_id}\n" if case_id else ""
            log_embed = obsidian_embed(
                "⚠️ Member Warned",
                f"{case_ref}**User:** {user.mention} ({user.id})\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}\n**Warnings:** {warning_count}/{max_warnings}",
                color=discord.Color.orange(),
                client=interaction.client,
                fields=[("Context", f"[Command run in {interaction.channel.mention}]({jump_url})", False)],
            )
            log_embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
            try:
                await log_channel.send(embed=log_embed)
            except discord.Forbidden:
                pass

    action_text = f" ({action} executed)" if warning_count >= max_warnings else ""
    case_ref = f"**Case #** {case_id}\n" if case_id else ""
    pct = min(100, int(100 * warning_count / max_warnings)) if max_warnings > 0 else 0
    bar_len = 8
    filled = int(bar_len * pct / 100)
    bar_str = "█" * filled + "░" * (bar_len - filled)
    warn_bar = f"`[{bar_str}]` {warning_count}/{max_warnings}"
    warn_fields = [
        ("User", user.mention, True),
        ("Moderator", interaction.user.mention, True),
        ("Reason", reason[:1024], False),
        ("Warning Count", warn_bar + action_text, True),
    ]
    case_bit = f"Case {copy_friendly_id(case_id)} · " if case_id else ""
    msg = await interaction.followup.send(
        embed=embed_template(
            "warning",
            "✅ User Warned",
            "",
            category="moderation",
            thumbnail=user.display_avatar.url if user.display_avatar else None,
            fields=warn_fields,
            footer=f"{case_bit}{footer_for('moderation_warn')}",
            client=interaction.client,
        )
    )

    if case_id:

        async def _undo_warn(undo_i: discord.Interaction):
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM warnings WHERE id=?", (case_id,))
                await db.commit()
            await undo_i.response.edit_message(
                embed=success_embed(
                    "Warning removed",
                    f"Undid warning case **#{case_id}** for {user.mention}.",
                    client=interaction.client,
                ),
                view=None,
            )

        from views._core import UndoView

        try:
            await msg.edit(view=UndoView(_undo_warn, requester_id=interaction.user.id, timeout=60))
        except Exception:
            pass


def setup(bot, group=None):
    """Register warn commands (warn moved to context menu, keep warnings and warn_setup)."""

    command_decorator = group.command(name="warnings", description="View a user's warnings.") if group else bot.tree.command(name="warnings", description="View a user's warnings.")

    @command_decorator
    @app_commands.describe(user="User to check")
    async def warnings(interaction: discord.Interaction, user: discord.Member):
        """View user warnings."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, moderator_id, reason, created_at FROM warnings
                WHERE guild_id=? AND user_id=? ORDER BY created_at DESC
            """, (interaction.guild.id, user.id))
            warnings_with_ids = await cur.fetchall()

            cur = await db.execute("""
                SELECT max_warnings FROM warn_settings WHERE guild_id=?
            """, (interaction.guild.id,))
            settings_row = await cur.fetchone()
            max_warnings = settings_row[0] if settings_row else 3

        if not warnings_with_ids:
            return await interaction.followup.send(
                embed=embed_template(
                    "showcase",
                    "⚠️ Warnings",
                    f"{user.mention} has no warnings.",
                    category="moderation",
                    footer=footer_for("moderation_warn"),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        per_page = 15
        lines = [
            f"{copy_friendly_id(wid)} {reason} - <t:{int(dateparser.parse(created_at, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}).timestamp())}:R>"
            for wid, mod_id, reason, created_at in warnings_with_ids
        ]
        if len(lines) <= per_page:
            warnings_text = "\n".join(lines)
            embed = embed_template(
                "warning",
                f"⚠️ Warnings for {user.display_name}",
                f"**Total:** {format_number(len(warnings_with_ids))}/{max_warnings} {pluralize(len(warnings_with_ids), 'warning')}\n\n{warnings_text}",
                category="moderation",
                footer=f"{footer_for('moderation_warn')} · Mod only",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            pages = []
            for i in range(0, len(lines), per_page):
                chunk = lines[i:i + per_page]
                pages.append({
                    "description": f"**Total:** {len(warnings_with_ids)}/{max_warnings}\n\n" + "\n".join(chunk),
                })
            view = EmbedPaginator(
                f"⚠️ Warnings for {user.display_name}",
                pages,
                color=EMBED_COLORS["moderation"],
                client=interaction.client,
            )
            await interaction.followup.send(
                embed=view._build_embed(),
                view=view,
                ephemeral=True,
            )

    clear_decorator = group.command(name="clear", description="Remove all warnings from a user (moderators only).") if group else None
    if clear_decorator:
        @clear_decorator
        @app_commands.describe(user="User to clear warnings for")
        async def warn_clear(interaction: discord.Interaction, user: discord.Member):
            """Clear all warnings for a user."""
            if not interaction.guild:
                return await interaction.response.send_message(
                    embed=error_embed("Invalid Context", "Use in a server.", client=interaction.client),
                    ephemeral=True,
                )
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                return await interaction.response.send_message(
                    embed=error_embed("Permission Denied", "Moderators only.", client=interaction.client),
                    ephemeral=True,
                )
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, user.id),
                )
                count = (await cur.fetchone())[0]
                if count == 0:
                    return await interaction.followup.send(
                        embed=obsidian_embed("⚠️ No Warnings", f"{user.mention} has no warnings.", color=discord.Color.green(), client=interaction.client),
                        ephemeral=True,
                    )
                await db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id))
                await db.commit()
            await interaction.followup.send(
                embed=obsidian_embed("✅ Warnings Cleared", f"Removed {count} warning(s) from {user.mention}.", color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )

    command_decorator = group.command(name="setup", description="Configure warn system (moderators only).") if group else bot.tree.command(name="setup", description="Configure warn system (moderators only).")
    
    @command_decorator
    @app_commands.describe(max_warnings="Maximum warnings before action", action="Action to take after max warnings", mute_duration="Mute duration in minutes (if action is mute)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Mute", value="mute"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    async def warn_setup(interaction: discord.Interaction, max_warnings: int, action: str, mute_duration: Optional[int] = None):
        """Configure warn system."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
                ephemeral=True
            )
        
        if max_warnings < 1:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Value", "Maximum warnings must be at least 1.", client=interaction.client),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO warn_settings (guild_id, max_warnings, action_after_max, mute_duration)
                VALUES (?, ?, ?, ?)
            """, (interaction.guild.id, max_warnings, action, mute_duration))
            await db.commit()
        
        await interaction.followup.send(
            embed=embed_template(
                "warning",
                "✅ Warn System Configured",
                f"**Max Warnings:** {max_warnings}\n**Action:** {action}\n"
                f"{f'**Mute Duration:** {mute_duration} minutes' if action == 'mute' and mute_duration else ''}",
                category="moderation",
                footer=footer_for("moderation_warn"),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # ----- Item 38: warn reason templates ---------------------------------------
    if group is None:
        return  # template commands only register under the warn group

    async def _reason_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []
        rows = await _list_templates(interaction.guild.id)
        cur_lower = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for name, template in rows:
            if cur_lower and cur_lower not in name.lower() and cur_lower not in template.lower():
                continue
            preview = template[:60] + ("…" if len(template) > 60 else "")
            label = f"{name} — {preview}"[:100]
            # value = name; the command body resolves to full template text.
            choices.append(app_commands.Choice(name=label, value=name[:100]))
            if len(choices) >= AUTOCOMPLETE_MAX_CHOICES:
                break
        return choices

    @group.command(name="quick", description="Warn a user using a saved reason template (or any text).")
    @app_commands.describe(user="User to warn", reason="Saved reason name OR raw text")
    @app_commands.autocomplete(reason=_reason_autocomplete)
    async def warn_quick(interaction: discord.Interaction, user: discord.Member, reason: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        # If `reason` is a saved template name, expand it. Otherwise treat as raw text.
        resolved = await _get_template(interaction.guild.id, reason) or reason
        await execute_warn(interaction, user, resolved)

    @group.command(name="template_add", description="Add or update a saved warn reason template (mods only).")
    @app_commands.describe(name="Short name (autocompleted later)", template="Full warning text")
    async def template_add(interaction: discord.Interaction, name: str, template: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        name = name.strip()
        template = template.strip()
        if not (1 <= len(name) <= 60):
            return await interaction.response.send_message(
                embed=error_embed("Bad name", "Name must be 1–60 chars.", client=interaction.client),
                ephemeral=True,
            )
        if not (1 <= len(template) <= 1500):
            return await interaction.response.send_message(
                embed=error_embed("Bad template", "Template must be 1–1500 chars.", client=interaction.client),
                ephemeral=True,
            )
        await _ensure_template_table()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO warn_reason_templates(guild_id, name, template, created_at, created_by)
                VALUES(?,?,?,?,?)
                ON CONFLICT(guild_id, name) DO UPDATE SET template=excluded.template
                """,
                (interaction.guild.id, name, template, now_utc().isoformat(), interaction.user.id),
            )
            await db.commit()
        await interaction.response.send_message(
            embed=success_embed("Template saved", f"`{name}` → _{template[:120]}_", client=interaction.client),
            ephemeral=True,
        )

    @group.command(name="template_remove", description="Delete a saved warn reason template (mods only).")
    @app_commands.describe(name="Template name to delete")
    @app_commands.autocomplete(name=_reason_autocomplete)
    async def template_remove(interaction: discord.Interaction, name: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Mods only", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        await _ensure_template_table()
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "DELETE FROM warn_reason_templates WHERE guild_id=? AND name=?",
                (interaction.guild.id, name),
            )
            await db.commit()
            removed = (cur.rowcount or 0) > 0
        if not removed:
            return await interaction.response.send_message(
                embed=error_embed("Not found", f"No template named `{name[:40]}`.", client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=success_embed("Template removed", f"`{name}` deleted.", client=interaction.client),
            ephemeral=True,
        )

    @group.command(name="template_list", description="List saved warn reason templates for this server.")
    async def template_list(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Use this in a server.", client=interaction.client),
                ephemeral=True,
            )
        rows = await _list_templates(interaction.guild.id)
        if not rows:
            return await interaction.response.send_message(
                embed=embed_template(
                    "showcase",
                    "No templates",
                    "No saved warn reasons yet. Mods can add one with `/warn template_add`.",
                    category="moderation",
                    footer=footer_for("moderation_warn"),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = [f"• `{name}` — {tmpl[:120]}{'…' if len(tmpl) > 120 else ''}" for name, tmpl in rows[:25]]
        await interaction.response.send_message(
            embed=obsidian_embed(
                "Saved warn reason templates",
                "\n".join(lines),
                color=EMBED_COLORS["moderation"],
                footer="Use the name in /mod warn quick reason:<name>",
                client=interaction.client,
            ),
            ephemeral=True,
        )
