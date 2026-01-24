"""Raid protection system - detect and prevent server raids."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timedelta, timezone

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def get_raid_settings(guild_id: int) -> dict:
    """Get raid protection settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT enabled, join_threshold, time_window_seconds, action,
                   lockdown_duration_minutes, alert_channel_id, alert_role_id
            FROM raid_protection_settings WHERE guild_id=?
        """, (guild_id,))
        row = await cur.fetchone()
        
        if row:
            return {
                "enabled": bool(row[0]),
                "join_threshold": row[1],
                "time_window_seconds": row[2],
                "action": row[3],
                "lockdown_duration_minutes": row[4],
                "alert_channel_id": row[5],
                "alert_role_id": row[6]
            }
        
        # Default settings
        return {
            "enabled": False,
            "join_threshold": 10,
            "time_window_seconds": 60,
            "action": "lockdown",
            "lockdown_duration_minutes": 30,
            "alert_channel_id": None,
            "alert_role_id": None
        }


async def record_join(guild_id: int, user_id: int, account_age_days: Optional[int] = None):
    """Record a member join for raid detection."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO recent_joins (guild_id, user_id, account_age_days, joined_at)
            VALUES (?, ?, ?, ?)
        """, (guild_id, user_id, account_age_days, now_utc().isoformat()))
        await db.commit()


async def check_raid_condition(guild: discord.Guild) -> tuple[bool, int]:
    """Check if raid conditions are met. Returns (is_raid, join_count)."""
    settings = await get_raid_settings(guild.id)
    
    if not settings["enabled"]:
        return False, 0
    
    # Get recent joins within time window
    time_window = timedelta(seconds=settings["time_window_seconds"])
    cutoff_time = (now_utc() - time_window).isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT COUNT(*) FROM recent_joins
            WHERE guild_id=? AND joined_at >= ?
        """, (guild.id, cutoff_time))
        row = await cur.fetchone()
        join_count = row[0] if row else 0
    
    is_raid = join_count >= settings["join_threshold"]
    return is_raid, join_count


async def trigger_raid_protection(guild: discord.Guild, join_count: int):
    """Trigger raid protection measures."""
    settings = await get_raid_settings(guild.id)
    
    # Send alert
    if settings["alert_channel_id"]:
        alert_channel = guild.get_channel(settings["alert_channel_id"])
        if isinstance(alert_channel, discord.TextChannel):
            try:
                alert_text = f"🚨 **RAID DETECTED** 🚨\n\n"
                alert_text += f"**{join_count}** members joined in the last {settings['time_window_seconds']} seconds.\n"
                alert_text += f"**Action:** {settings['action']}\n\n"
                
                if settings["alert_role_id"]:
                    role = guild.get_role(settings["alert_role_id"])
                    if role:
                        alert_text = f"{role.mention} {alert_text}"
                
                await alert_channel.send(alert_text)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error sending raid alert: {e}")
    
    # Execute action
    if settings["action"] == "lockdown":
        # Lockdown: disable @everyone from sending messages
        try:
            everyone_role = guild.default_role
            if guild.me.guild_permissions.manage_channels:
                # Disable send_messages for @everyone
                overwrite = discord.PermissionOverwrite(send_messages=False)
                for channel in guild.channels:
                    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                        try:
                            await channel.set_permissions(everyone_role, overwrite=overwrite)
                        except discord.Forbidden:
                            pass
                
                # Schedule unlock after duration
                if settings["lockdown_duration_minutes"] > 0:
                    # Store unlock time in database (would need a task to check and unlock)
                    unlock_time = (now_utc() + timedelta(minutes=settings["lockdown_duration_minutes"])).isoformat()
                    # Could store this in a table for a background task to process
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error executing raid lockdown: {e}")


def setup(bot, group=None):
    """Register raid protection commands."""
    # Raid protection settings command
    settings_decorator = group.command(name="raid_protection", description="Configure raid protection (moderators only).") if group else bot.tree.command(name="raid_protection", description="Configure raid protection (moderators only).")
    
    @settings_decorator
    @app_commands.describe(
        enabled="Enable or disable raid protection",
        join_threshold="Number of joins to trigger protection (default: 10)",
        time_window_seconds="Time window in seconds (default: 60)",
        action="Action to take when raid detected",
        lockdown_duration_minutes="Lockdown duration in minutes (default: 30)",
        alert_channel="Channel to send raid alerts to",
        alert_role="Role to ping when raid detected"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Lockdown", value="lockdown"),
        app_commands.Choice(name="Alert Only", value="alert"),
    ])
    async def raid_protection(
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        join_threshold: Optional[int] = None,
        time_window_seconds: Optional[int] = None,
        action: Optional[str] = None,
        lockdown_duration_minutes: Optional[int] = None,
        alert_channel: Optional[discord.TextChannel] = None,
        alert_role: Optional[discord.Role] = None
    ):
        """Configure raid protection."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can configure raid protection.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        current_settings = await get_raid_settings(interaction.guild.id)
        
        # Update settings
        new_enabled = enabled if enabled is not None else current_settings["enabled"]
        new_threshold = join_threshold if join_threshold is not None else current_settings["join_threshold"]
        new_window = time_window_seconds if time_window_seconds is not None else current_settings["time_window_seconds"]
        new_action = action if action else current_settings["action"]
        new_duration = lockdown_duration_minutes if lockdown_duration_minutes is not None else current_settings["lockdown_duration_minutes"]
        new_alert_channel = alert_channel.id if alert_channel else current_settings["alert_channel_id"]
        new_alert_role = alert_role.id if alert_role else current_settings["alert_role_id"]
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO raid_protection_settings
                (guild_id, enabled, join_threshold, time_window_seconds, action,
                 lockdown_duration_minutes, alert_channel_id, alert_role_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    join_threshold = excluded.join_threshold,
                    time_window_seconds = excluded.time_window_seconds,
                    action = excluded.action,
                    lockdown_duration_minutes = excluded.lockdown_duration_minutes,
                    alert_channel_id = excluded.alert_channel_id,
                    alert_role_id = excluded.alert_role_id
            """, (interaction.guild.id, new_enabled, new_threshold, new_window, new_action,
                  new_duration, new_alert_channel, new_alert_role))
            await db.commit()
        
        alert_channel_text = alert_channel.mention if alert_channel else (f"<#{new_alert_channel}>" if new_alert_channel else "Not set")
        alert_role_text = alert_role.mention if alert_role else (f"<@&{new_alert_role}>" if new_alert_role else "Not set")
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Raid Protection Settings Updated",
                f"**Enabled:** {new_enabled}\n"
                f"**Join Threshold:** {new_threshold} members\n"
                f"**Time Window:** {new_window} seconds\n"
                f"**Action:** {new_action}\n"
                f"**Lockdown Duration:** {new_duration} minutes\n"
                f"**Alert Channel:** {alert_channel_text}\n"
                f"**Alert Role:** {alert_role_text}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
