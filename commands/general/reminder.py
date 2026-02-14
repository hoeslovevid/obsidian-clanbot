"""Reminder system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone, timedelta
import dateparser

from config import TIMEZONE
from utils import obsidian_embed, TIME_AUTOCOMPLETE_CHOICES, EMBED_COLORS
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
        remind_time = dateparser.parse(when, settings={'TIMEZONE': tz_for_parse, 'RETURN_AS_TIMEZONE_AWARE': True, 'TO_TIMEZONE': 'UTC'}, relative_base=datetime.now(timezone.utc))
        
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
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Reminder Set",
                f"**Reminder:** {reminder}\n**When:** <t:{int(remind_time.timestamp())}:F> (<t:{int(remind_time.timestamp())}:R>){repeat_text}",
                color=EMBED_COLORS["success"],
                client=interaction.client,
            ),
            ephemeral=True
        )

    # Reminder preferences (mods only) - quieter notifications via DM
    from utils import is_mod
    list_decorator = group.command(name="remind_list", description="List your pending reminders. Optionally cancel one.") if group else bot.tree.command(name="remind_list", description="List your pending reminders.")

    @list_decorator
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
                return await interaction.followup.send(
                    embed=obsidian_embed("✅ Cancelled", f"Reminder '{row[1][:50]}...' cancelled." if len(row[1]) > 50 else f"Reminder '{row[1]}' cancelled.", color=EMBED_COLORS["success"], client=interaction.client),
                    ephemeral=True,
                )
            cur = await db.execute(
                "SELECT id, reminder_text, remind_at, recurrence_rule FROM reminders WHERE guild_id=? AND user_id=? AND sent=0 AND datetime(remind_at) > datetime('now') ORDER BY remind_at ASC LIMIT 50",
                (interaction.guild.id, interaction.user.id),
            )
            rows_raw = await cur.fetchall()
            rows = [(r[0], r[1], r[2], r[3] if len(r) > 3 else None) for r in rows_raw]
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed("📋 No Pending Reminders", "You have no active reminders. Use `/tools remind` to set one.", color=discord.Color.blue(), client=interaction.client),
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
