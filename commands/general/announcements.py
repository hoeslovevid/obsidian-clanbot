"""Scheduled announcements system."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timedelta, timezone
import dateparser

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite
import json


async def get_scheduled_announcements(guild_id: int) -> list:
    """Get all scheduled announcements for a guild."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, channel_id, message_text, embed_json, schedule_type, schedule_value,
                   next_run_at, enabled, created_by
            FROM scheduled_announcements
            WHERE guild_id=? AND enabled=1
            ORDER BY next_run_at ASC
        """, (guild_id,))
        return await cur.fetchall()


async def create_scheduled_announcement(
    guild_id: int,
    channel_id: int,
    message_text: str,
    schedule_type: str,
    schedule_value: str,
    creator_id: int,
    embed_json: Optional[str] = None
) -> int:
    """Create a scheduled announcement. Returns the announcement ID."""
    # Calculate next run time based on schedule type
    now = now_utc()
    next_run = None
    
    if schedule_type == "daily":
        # Parse time (e.g., "14:30" or "2:30 PM")
        try:
            time_obj = dateparser.parse(schedule_value, settings={'PREFER_DATES_FROM': 'future'})
            if time_obj:
                next_run = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
        except:
            # Default to current time + 1 day
            next_run = now + timedelta(days=1)
    
    elif schedule_type == "weekly":
        # schedule_value should be day of week (0-6) and time
        # Format: "monday 14:30" or "1 14:30"
        try:
            parts = schedule_value.split()
            day_str = parts[0]
            time_str = parts[1] if len(parts) > 1 else "12:00"
            
            # Parse day
            days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            day_num = days.get(day_str.lower(), int(day_str))
            
            # Parse time
            time_obj = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future'})
            target_time = time_obj.hour if time_obj else 12, time_obj.minute if time_obj else 0
            
            # Calculate next occurrence
            days_until = (day_num - now.weekday()) % 7
            if days_until == 0:
                # Check if time has passed today
                if now.hour > target_time[0] or (now.hour == target_time[0] and now.minute >= target_time[1]):
                    days_until = 7
            
            next_run = now + timedelta(days=days_until)
            next_run = next_run.replace(hour=target_time[0], minute=target_time[1], second=0, microsecond=0)
        except:
            next_run = now + timedelta(days=7)
    
    elif schedule_type == "interval":
        # schedule_value is minutes/hours/days (e.g., "30 minutes", "2 hours", "1 day")
        try:
            parsed = dateparser.parse(f"in {schedule_value}", settings={'RELATIVE_BASE': now})
            if parsed:
                next_run = parsed
            else:
                next_run = now + timedelta(hours=1)
        except:
            next_run = now + timedelta(hours=1)
    
    if not next_run:
        next_run = now + timedelta(days=1)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO scheduled_announcements
            (guild_id, channel_id, message_text, embed_json, schedule_type, schedule_value,
             next_run_at, enabled, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (guild_id, channel_id, message_text, embed_json, schedule_type, schedule_value,
              next_run.isoformat(), creator_id, now_utc().isoformat()))
        await db.commit()
        
        cur = await db.execute("SELECT last_insert_rowid()")
        return (await cur.fetchone())[0]


async def update_next_run(announcement_id: int, schedule_type: str, schedule_value: str):
    """Update the next run time for an announcement."""
    now = now_utc()
    next_run = None
    
    if schedule_type == "daily":
        try:
            time_obj = dateparser.parse(schedule_value)
            if time_obj:
                next_run = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
        except:
            next_run = now + timedelta(days=1)
    
    elif schedule_type == "weekly":
        try:
            parts = schedule_value.split()
            day_str = parts[0]
            time_str = parts[1] if len(parts) > 1 else "12:00"
            days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            day_num = days.get(day_str.lower(), int(day_str))
            time_obj = dateparser.parse(time_str)
            target_time = (time_obj.hour if time_obj else 12, time_obj.minute if time_obj else 0)
            days_until = (day_num - now.weekday()) % 7
            if days_until == 0:
                if now.hour > target_time[0] or (now.hour == target_time[0] and now.minute >= target_time[1]):
                    days_until = 7
            next_run = now + timedelta(days=days_until)
            next_run = next_run.replace(hour=target_time[0], minute=target_time[1], second=0, microsecond=0)
        except:
            next_run = now + timedelta(days=7)
    
    elif schedule_type == "interval":
        try:
            parsed = dateparser.parse(f"in {schedule_value}", settings={'RELATIVE_BASE': now})
            next_run = parsed if parsed else now + timedelta(hours=1)
        except:
            next_run = now + timedelta(hours=1)
    
    if next_run:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE scheduled_announcements
                SET next_run_at = ?
                WHERE id = ?
            """, (next_run.isoformat(), announcement_id))
            await db.commit()


def setup(bot, group=None):
    """Register announcement commands."""
    # Create announcement command
    create_decorator = group.command(name="announcement", description="Manage scheduled announcements (moderators only).") if group else bot.tree.command(name="announcement", description="Manage scheduled announcements (moderators only).")
    
    @create_decorator
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to send announcements to",
        message="Message text for the announcement",
        schedule_type="How often to send",
        schedule_value="Schedule value (e.g., '14:30' for daily, 'monday 14:30' for weekly, '30 minutes' for interval)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create", value="create"),
        app_commands.Choice(name="List", value="list"),
        app_commands.Choice(name="Delete", value="delete"),
    ])
    @app_commands.choices(schedule_type=[
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Interval", value="interval"),
    ])
    async def announcement(
        interaction: discord.Interaction,
        action: str,
        channel: Optional[discord.TextChannel] = None,
        message: Optional[str] = None,
        schedule_type: Optional[str] = None,
        schedule_value: Optional[str] = None
    ):
        """Manage scheduled announcements."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can manage scheduled announcements.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        if action == "create":
            if not channel or not message or not schedule_type or not schedule_value:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please provide: channel, message, schedule_type, and schedule_value.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            announcement_id = await create_scheduled_announcement(
                interaction.guild.id,
                channel.id,
                message,
                schedule_type,
                schedule_value,
                interaction.user.id
            )
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Announcement Scheduled",
                    f"Announcement #{announcement_id} has been scheduled.\n\n"
                    f"**Channel:** {channel.mention}\n"
                    f"**Schedule:** {schedule_type} ({schedule_value})",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action == "list":
            announcements = await get_scheduled_announcements(interaction.guild.id)
            
            if not announcements:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Scheduled Announcements",
                        "No scheduled announcements found.",
                        color=discord.Color.blurple(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            fields = []
            for ann_id, ch_id, msg_text, embed_json, sched_type, sched_value, next_run, enabled, creator_id in announcements[:10]:
                ch = interaction.guild.get_channel(ch_id)
                channel_name = ch.mention if ch else f"Channel {ch_id}"
                msg_preview = msg_text[:50] + "..." if len(msg_text) > 50 else msg_text
                fields.append((
                    f"#{ann_id} - {sched_type.title()}",
                    f"**Channel:** {channel_name}\n"
                    f"**Message:** {msg_preview}\n"
                    f"**Schedule:** {sched_value}\n"
                    f"**Next Run:** {next_run[:16] if next_run else 'Unknown'}",
                    False
                ))
            
            embed = obsidian_embed(
                "📋 Scheduled Announcements",
                f"**Total:** {len(announcements)} active announcement(s)",
                color=discord.Color.blurple(),
                fields=fields,
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action == "delete":
            # This would need an announcement_id parameter
            await interaction.followup.send(
                embed=obsidian_embed(
                    "ℹ️ Delete Announcement",
                    "Use `/announcement delete` with an announcement ID to delete a specific announcement.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
