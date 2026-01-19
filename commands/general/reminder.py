"""Reminder system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import dateparser

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register reminder commands."""
    
    command_decorator = group.command(name="remind", description="Set a reminder.") if group else bot.tree.command(name="remind", description="Set a reminder.")
    
    @command_decorator
    @app_commands.describe(when="When to remind you (e.g., 'in 2 hours', 'tomorrow at 3pm')", reminder="What to remind you about")
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
        
        # Parse when
        remind_time = dateparser.parse(when, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True}, relative_base=datetime.now(timezone.utc))
        
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
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
