"""Reminder system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta
import dateparser

from core.embed_templates import embed_template
from core.user_time import format_user_time
from core.utils import obsidian_embed, TIME_AUTOCOMPLETE_CHOICES, EMBED_COLORS
from database import DB_PATH, now_utc, get_user_timezone
import aiosqlite


def _next_recurrence(remind_at: datetime, rule: str) -> Optional[datetime]:
    """Compute next remind_at from recurrence rule. remind_at is UTC."""
    if not rule:
        return None
    if rule == "daily":
        return remind_at + timedelta(days=1)
    if rule.startswith("weekly:"):
        try:
            return remind_at + timedelta(days=7)
        except Exception:
            return None
    if rule.startswith("monthly:"):
        try:
            y, m = remind_at.year, remind_at.month
            m += 1
            if m > 12:
                m, y = 1, y + 1
            return remind_at.replace(year=y, month=m)
        except ValueError:
            return remind_at + timedelta(days=28)
    return None


class ReminderSnoozeView(discord.ui.View):
    """Snooze buttons attached to a delivered reminder (re-schedules it)."""

    def __init__(self, *, guild_id: int, user_id: int, channel_id: Optional[int], reminder_text: str):
        super().__init__(timeout=6 * 3600)  # buttons stay live for 6 hours
        self.guild_id = guild_id
        self.user_id = user_id
        self.channel_id = channel_id
        self.reminder_text = reminder_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person being reminded can snooze this.", ephemeral=True
            )
            return False
        return True

    async def _snooze(self, interaction: discord.Interaction, minutes: int) -> None:
        from core.db import open_db

        remind_at = now_utc() + timedelta(minutes=minutes)
        try:
            async with open_db() as db:
                await db.execute(
                    """
                    INSERT INTO reminders (guild_id, user_id, channel_id, reminder_text, remind_at, created_at, sent, recurrence_rule)
                    VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (
                        self.guild_id,
                        self.user_id,
                        self.channel_id,
                        self.reminder_text,
                        remind_at.isoformat(),
                        now_utc().isoformat(),
                    ),
                )
                await db.commit()
        except Exception:
            return await interaction.response.send_message(
                "Couldn't snooze that reminder — please set a new one with `/tools remind`.",
                ephemeral=True,
            )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            f"⏰ Snoozed — I'll remind you again <t:{int(remind_at.timestamp())}:R>.",
            ephemeral=True,
        )

    @discord.ui.button(label="+10 min", emoji="⏱️", style=discord.ButtonStyle.secondary)
    async def snooze_10m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._snooze(interaction, 10)

    @discord.ui.button(label="+1 hour", emoji="🕐", style=discord.ButtonStyle.secondary)
    async def snooze_1h(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._snooze(interaction, 60)

    @discord.ui.button(label="Tomorrow", emoji="📅", style=discord.ButtonStyle.secondary)
    async def snooze_1d(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._snooze(interaction, 60 * 24)


async def remind_when_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for natural time strings."""
    current_lower = (current or "").lower()
    choices = []
    for value, label in TIME_AUTOCOMPLETE_CHOICES:
        if not current_lower or current_lower in value.lower():
            choices.append(app_commands.Choice(name=label, value=value))
    return choices[:25]


def setup(bot, group=None):
    """Register reminder commands."""
    
    command_decorator = group.command(name="remind", description="Set a reminder. Example: /tools remind when:in 2 hours reminder:Join voice") if group else bot.tree.command(name="remind", description="Set a reminder. Example: /tools remind when:in 2 hours reminder:Join voice")
    
    @command_decorator
    @app_commands.autocomplete(when=remind_when_autocomplete)
    @app_commands.describe(
        when="When to remind: 'in 2 hours', 'tomorrow 8pm', 'every Monday 8pm', etc.",
        reminder="What to remind you about",
        repeat="Repeat this reminder (e.g. every Monday 8pm → Weekly)"
    )
    @app_commands.choices(repeat=[
        app_commands.Choice(name="No - one time only", value="none"),
        app_commands.Choice(name="Daily - same time every day", value="daily"),
        app_commands.Choice(name="Weekly - same day and time", value="weekly"),
        app_commands.Choice(name="Monthly - same date and time", value="monthly"),
    ])
    async def remind(interaction: discord.Interaction, when: str, reminder: str, repeat: app_commands.Choice[str] = None):
        """Set a reminder."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)

        # Parse when (use user timezone if set, else server default)
        user_tz = await get_user_timezone(interaction.guild.id, interaction.user.id)
        tz_for_parse = user_tz or TIMEZONE
        remind_time = dateparser.parse(
            when,
            settings={
                'TIMEZONE': tz_for_parse,
                'RETURN_AS_TIMEZONE_AWARE': True,
                'TO_TIMEZONE': 'UTC',
                'RELATIVE_BASE': datetime.now(timezone.utc),
            },
        )
        
        if not remind_time:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Time",
                    f"Could not parse '{when}'.\n\n**Try formats like:**\n• `in 2 hours`\n• `tomorrow 8pm`\n• `next Friday 3pm`\n• `2025-01-20 14:00`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check if time is in the past
        if remind_time <= datetime.now(timezone.utc):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Time",
                    "The reminder time must be in the future.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        recurrence_rule = None
        if repeat and repeat.value != "none":
            if repeat.value == "daily":
                recurrence_rule = "daily"
            elif repeat.value == "weekly":
                recurrence_rule = f"weekly:{remind_time.weekday()}"
            elif repeat.value == "monthly":
                recurrence_rule = f"monthly:{remind_time.day}"
        
        # Store reminder
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO reminders (guild_id, user_id, channel_id, reminder_text, remind_at, created_at, sent, recurrence_rule)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """, (interaction.guild.id, interaction.user.id, interaction.channel.id, reminder, remind_time.isoformat(), now_utc().isoformat(), recurrence_rule))
            await db.commit()

        repeat_text = f"\n**Repeats:** {repeat.name.split(' - ')[0]}" if recurrence_rule else ""
        when_display = await format_user_time(
            interaction.guild.id, interaction.user.id, remind_time, include_relative=True
        )
        await interaction.followup.send(
            embed=embed_template(
                "showcase",
                "✅ Reminder Set",
                f"**Reminder:** {reminder}\n**When:** {when_display}{repeat_text}",
                category="general",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # Reminder preferences (mods only) - quieter notifications via DM
    from core.utils import is_mod
    list_decorator = group.command(name="remind_list", description="List your pending reminders. Optionally cancel one.") if group else bot.tree.command(name="remind_list", description="List your pending reminders.")

    async def remind_cancel_autocomplete(interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        from core.db import open_db

        try:
            async with open_db() as db:
                cur = await db.execute(
                    "SELECT id, reminder_text FROM reminders WHERE guild_id=? AND user_id=? AND sent=0 "
                    "AND datetime(remind_at) > datetime('now') ORDER BY remind_at ASC LIMIT 25",
                    (interaction.guild.id, interaction.user.id),
                )
                rows = await cur.fetchall()
        except Exception:
            return []
        cur_s = (current or "").strip().lower()
        choices = []
        for rid, text in rows:
            if cur_s and cur_s not in str(rid) and cur_s not in (text or "").lower():
                continue
            label = f"#{rid}: {text}"[:100]
            choices.append(app_commands.Choice(name=label, value=int(rid)))
        return choices[:25]

    @list_decorator
    @app_commands.autocomplete(cancel_id=remind_cancel_autocomplete)
    @app_commands.describe(cancel_id="Optional: reminder ID to cancel (from list)")
    async def remind_list(interaction: discord.Interaction, cancel_id: Optional[int] = None):
        """List or cancel reminders."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "Use this in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            if cancel_id is not None:
                cur = await db.execute(
                    "SELECT id, reminder_text, remind_at FROM reminders WHERE guild_id=? AND user_id=? AND id=? AND sent=0",
                    (interaction.guild.id, interaction.user.id, cancel_id),
                )
                row = await cur.fetchone()
                if not row:
                    return await interaction.followup.send(
                        embed=obsidian_embed("❌ Not Found", f"Reminder #{cancel_id} not found or already sent.", color=discord.Color.red(), client=interaction.client),
                        ephemeral=True,
                    )
                await db.execute("DELETE FROM reminders WHERE id=?", (cancel_id,))
                await db.commit()

                from views._core import UndoView

                deleted_text = row[1]
                deleted_when = row[2]
                cancel_channel_id = interaction.channel_id

                async def _undo_cancel(undo_i: discord.Interaction):
                    from core.db import open_db

                    async with open_db() as db2:
                        await db2.execute(
                            """
                            INSERT INTO reminders (guild_id, user_id, channel_id, reminder_text, remind_at, created_at, sent, recurrence_rule)
                            VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                            """,
                            (
                                undo_i.guild.id,
                                undo_i.user.id,
                                cancel_channel_id,
                                deleted_text,
                                deleted_when,
                                now_utc().isoformat(),
                            ),
                        )
                        await db2.commit()
                    await undo_i.response.edit_message(
                        embed=obsidian_embed(
                            "↩️ Reminder Restored",
                            "Your reminder is back on the schedule.",
                            color=EMBED_COLORS["success"],
                            client=undo_i.client,
                        ),
                        view=None,
                    )

                shown = f"{deleted_text[:50]}..." if len(deleted_text) > 50 else deleted_text
                undo_view = UndoView(_undo_cancel, requester_id=interaction.user.id, timeout=60)
                msg = await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Cancelled",
                        f"Reminder '{shown}' cancelled.",
                        color=EMBED_COLORS["success"],
                        client=interaction.client,
                    ),
                    view=undo_view,
                    ephemeral=True,
                )
                undo_view.message = msg
                return
            cur = await db.execute(
                "SELECT id, reminder_text, remind_at, recurrence_rule FROM reminders WHERE guild_id=? AND user_id=? AND sent=0 AND datetime(remind_at) > datetime('now') ORDER BY remind_at ASC LIMIT 50",
                (interaction.guild.id, interaction.user.id),
            )
            rows_raw = await cur.fetchall()
            rows = [(r[0], r[1], r[2], r[3] if len(r) > 3 else None) for r in rows_raw]
        if not rows:
            from core.utils import empty_state_embed
            return await interaction.followup.send(
                embed=empty_state_embed(
                    "📋 No Pending Reminders",
                    "You have no active reminders yet.",
                    suggestions=["tools remind"],
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        per_page = 15
        if len(rows) <= per_page:
            lines = []
            for row in rows:
                rid, text, remind_at = row[0], row[1], row[2]
                recurring = " 🔄" if len(row) > 3 and row[3] else ""
                try:
                    dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                    lines.append(f"**#{rid}**{recurring} — {text[:60]}{'…' if len(text) > 60 else ''}\n<t:{ts}:R> (<t:{ts}:t>)")
                except Exception:
                    lines.append(f"**#{rid}**{recurring} — {text[:60]} — {remind_at}")
            embed = obsidian_embed(
                "📋 Your Reminders",
                "\n\n".join(lines),
                color=discord.Color.blue(),
                footer="To cancel: /tools remind_list cancel_id:<id>",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            pages = []
            for i in range(0, len(rows), per_page):
                chunk = rows[i:i + per_page]
                lines = []
                for row in chunk:
                    rid, text, remind_at = row[0], row[1], row[2]
                    recurring = " 🔄" if len(row) > 3 and row[3] else ""
                    try:
                        dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
                        ts = int(dt.timestamp())
                        lines.append(f"**#{rid}**{recurring} — {text[:50]}{'…' if len(text) > 50 else ''}\n<t:{ts}:R>")
                    except Exception:
                        lines.append(f"**#{rid}**{recurring} — {text[:50]}")
                pages.append({"description": "\n\n".join(lines)})
            from views import EmbedPaginator
            view = EmbedPaginator(
                "📋 Your Reminders", pages, color=discord.Color.blue(), client=interaction.client,
                total_items=len(rows), per_page=per_page
            )
            await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)

    pref_decorator = group.command(name="reminder_prefs", description="Set reminder delivery preference (mods: DM vs channel).") if group else bot.tree.command(name="reminder_prefs", description="Set reminder delivery preference (mods: DM vs channel).")

    @pref_decorator
    @app_commands.describe(prefer_dm="If enabled, reminders are sent via DM when possible (quieter)")
    @app_commands.choices(prefer_dm=[
        app_commands.Choice(name="Yes - Prefer DM (quieter)", value="1"),
        app_commands.Choice(name="No - Always use channel", value="0"),
    ])
    async def reminder_prefs(interaction: discord.Interaction, prefer_dm: app_commands.Choice[str]):
        """Set whether reminders prefer DM delivery."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        from database import set_guild_setting
        await set_guild_setting(interaction.guild.id, "reminders_prefer_dm", prefer_dm.value)
        msg = "Reminders will be sent via DM when possible." if prefer_dm.value == "1" else "Reminders will be posted in the channel where they were set."
        await interaction.response.send_message(embed=obsidian_embed("✅ Preference Updated", msg, color=EMBED_COLORS["success"], client=interaction.client), ephemeral=True)
