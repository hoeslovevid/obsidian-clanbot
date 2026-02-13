"""Reminder system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import dateparser

from config import TIMEZONE
from utils import obsidian_embed, TIME_AUTOCOMPLETE_CHOICES, EMBED_COLORS
from database import DB_PATH, now_utc
import aiosqlite


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
    
    command_decorator = group.command(name="remind", description="Set a reminder. Example: /community remind when:in 2 hours reminder:Join voice") if group else bot.tree.command(name="remind", description="Set a reminder. Example: /community remind when:in 2 hours reminder:Join voice")
    
    @command_decorator
    @app_commands.autocomplete(when=remind_when_autocomplete)
    @app_commands.describe(when="When to remind: 'in 2 hours', 'tomorrow 8pm', etc.", reminder="What to remind you about")
    async def remind(interaction: discord.Interaction, when: str, reminder: str):
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
        
        # Parse when (use configured timezone)
        remind_time = dateparser.parse(when, settings={'TIMEZONE': TIMEZONE, 'RETURN_AS_TIMEZONE_AWARE': True, 'TO_TIMEZONE': 'UTC'}, relative_base=datetime.now(timezone.utc))
        
        if not remind_time:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Time",
                    f"Could not parse '{when}'. Try formats like 'in 2 hours', 'tomorrow at 3pm', or '2024-01-20 14:00'.",
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
        
        # Store reminder
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO reminders (guild_id, user_id, channel_id, reminder_text, remind_at, created_at, sent)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (interaction.guild.id, interaction.user.id, interaction.channel.id, reminder, remind_time.isoformat(), now_utc().isoformat()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Reminder Set",
                f"**Reminder:** {reminder}\n**When:** <t:{int(remind_time.timestamp())}:F> (<t:{int(remind_time.timestamp())}:R>)",
                color=EMBED_COLORS["success"],
                client=interaction.client,
            ),
            ephemeral=True
        )

    # Reminder preferences (mods only) - quieter notifications via DM
    from utils import is_mod
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
