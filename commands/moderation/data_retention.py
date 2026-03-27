"""Data retention policy management and cleanup commands."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def cleanup_old_data(guild_id: int, retention_days: dict) -> dict:
    """Clean up old data based on retention policies. Returns cleanup statistics."""
    stats = {
        "deleted_messages": 0,
        "edited_messages": 0,
        "auto_mod_violations": 0,
        "complaint_actions": 0,
        "event_rsvps": 0,
        "economy_transactions": 0,
        "activity_log": 0,
        "gambling_history": 0,
    }
    
    cutoff_date = now_utc() - timedelta(days=max(retention_days.values()) if retention_days else 90)
    cutoff_iso = cutoff_date.isoformat()
    
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        # Clean up deleted messages (default: 30 days)
        days = retention_days.get("deleted_messages", 30)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM deleted_messages
                WHERE guild_id=? AND deleted_at < ?
            """, (guild_id, cutoff))
            stats["deleted_messages"] = cur.rowcount
            await db.commit()
        
        # Clean up edited messages (default: 30 days)
        days = retention_days.get("edited_messages", 30)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM edited_messages
                WHERE guild_id=? AND edited_at < ?
            """, (guild_id, cutoff))
            stats["edited_messages"] = cur.rowcount
            await db.commit()
        
        # Clean up auto-mod violations (default: 90 days)
        days = retention_days.get("auto_mod_violations", 90)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM auto_mod_violations
                WHERE guild_id=? AND created_at < ?
            """, (guild_id, cutoff))
            stats["auto_mod_violations"] = cur.rowcount
            await db.commit()
        
        # Clean up old complaint actions (default: 180 days, but keep if complaint is still open)
        days = retention_days.get("complaint_actions", 180)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            # Only delete actions for closed complaints
            cur = await db.execute("""
                DELETE FROM complaint_actions
                WHERE guild_id=? AND created_at < ? AND case_id IN (
                    SELECT case_id FROM complaints WHERE guild_id=? AND status IN ('CLOSED', 'RESOLVED')
                )
            """, (guild_id, cutoff, guild_id))
            stats["complaint_actions"] = cur.rowcount
            await db.commit()
        
        # Clean up old event RSVPs (default: 90 days after event)
        days = retention_days.get("event_rsvps", 90)
        if days > 0:
            cutoff_ts = int((now_utc() - timedelta(days=days)).timestamp())
            cur = await db.execute("""
                DELETE FROM event_rsvps
                WHERE guild_id=? AND message_id IN (
                    SELECT message_id FROM events WHERE guild_id=? AND start_ts < ?
                )
            """, (guild_id, guild_id, cutoff_ts))
            stats["event_rsvps"] = cur.rowcount
            await db.commit()
        
        # Clean up old economy transactions (default: 365 days)
        days = retention_days.get("economy_transactions", 365)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM economy_transactions
                WHERE guild_id=? AND created_at < ?
            """, (guild_id, cutoff))
            stats["economy_transactions"] = cur.rowcount
            await db.commit()
        
        # Clean up old activity log entries (default: 180 days)
        days = retention_days.get("activity_log", 180)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM activity_log
                WHERE guild_id=? AND activity_date < ?
            """, (guild_id, cutoff))
            stats["activity_log"] = cur.rowcount
            await db.commit()
        
        # Clean up old gambling history (default: 90 days)
        days = retention_days.get("gambling_history", 90)
        if days > 0:
            cutoff = (now_utc() - timedelta(days=days)).isoformat()
            cur = await db.execute("""
                DELETE FROM gambling_history
                WHERE guild_id=? AND created_at < ?
            """, (guild_id, cutoff))
            stats["gambling_history"] = cur.rowcount
            await db.commit()
    
    return stats


async def get_retention_settings(guild_id: int) -> dict:
    """Get current retention policy settings."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT key, value FROM guild_settings
            WHERE guild_id=? AND key LIKE 'retention_%'
        """, (guild_id,))
        rows = await cur.fetchall()
    
    settings = {
        "deleted_messages": 30,
        "edited_messages": 30,
        "auto_mod_violations": 90,
        "complaint_actions": 180,
        "event_rsvps": 90,
        "economy_transactions": 365,
        "activity_log": 180,
        "gambling_history": 90,
    }
    
    for key, value in rows:
        setting_name = key.replace("retention_", "")
        try:
            settings[setting_name] = int(value)
        except ValueError:
            pass
    
    return settings


async def set_retention_setting(guild_id: int, setting_name: str, days: int):
    """Set a retention policy setting."""
    from database import set_guild_setting
    await set_guild_setting(guild_id, f"retention_{setting_name}", str(days))


def setup(bot, group=None):
    """Register data retention commands."""
    # Retention settings command
    retention_decorator = group.command(name="retention", description="Configure data retention policies (moderators only).") if group else bot.tree.command(name="retention", description="Configure data retention policies (moderators only).")
    
    @retention_decorator
    @app_commands.describe(
        action="Action to perform",
        data_type="Type of data to configure",
        days="Number of days to retain data (0 to disable retention for this type)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="View Settings", value="view"),
        app_commands.Choice(name="Set Retention", value="set"),
        app_commands.Choice(name="Run Cleanup", value="cleanup"),
    ])
    @app_commands.choices(data_type=[
        app_commands.Choice(name="Deleted Messages", value="deleted_messages"),
        app_commands.Choice(name="Edited Messages", value="edited_messages"),
        app_commands.Choice(name="Auto-Mod Violations", value="auto_mod_violations"),
        app_commands.Choice(name="Complaint Actions", value="complaint_actions"),
        app_commands.Choice(name="Event RSVPs", value="event_rsvps"),
        app_commands.Choice(name="Economy Transactions", value="economy_transactions"),
        app_commands.Choice(name="Activity Log", value="activity_log"),
        app_commands.Choice(name="Gambling History", value="gambling_history"),
    ])
    async def retention_command(
        interaction: discord.Interaction,
        action: str,
        data_type: Optional[str] = None,
        days: Optional[int] = None
    ):
        """Manage data retention policies."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can manage data retention policies.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        
        if action == "view":
            settings = await get_retention_settings(interaction.guild.id)
            
            fields = []
            for key, value in settings.items():
                status = f"{value} days" if value > 0 else "Disabled"
                fields.append((key.replace("_", " ").title(), status, True))
            
            embed = obsidian_embed(
                "📋 Data Retention Policies",
                "Current retention settings for this server.\n\n"
                "**Note:** These settings determine how long data is kept before automatic cleanup.",
                color=discord.Color.blurple(),
                fields=fields,
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
        elif action == "set":
            if not data_type or days is None:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please specify both `data_type` and `days` parameters.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if days < 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Value",
                        "Days must be 0 or greater. Use 0 to disable retention for this data type.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_retention_setting(interaction.guild.id, data_type, days)
            
            status = f"{days} days" if days > 0 else "Disabled"
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Retention Policy Updated",
                    f"Retention for **{data_type.replace('_', ' ').title()}** set to: **{status}**",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action == "cleanup":
            settings = await get_retention_settings(interaction.guild.id)
            stats = await cleanup_old_data(interaction.guild.id, settings)
            
            total_deleted = sum(stats.values())
            
            if total_deleted == 0:
                message = "No old data found to clean up."
            else:
                message = f"Cleanup completed. **{total_deleted:,}** records deleted:\n\n"
                for key, count in stats.items():
                    if count > 0:
                        message += f"• {key.replace('_', ' ').title()}: {count:,}\n"
            
            embed = obsidian_embed(
                "🧹 Data Cleanup Complete",
                message,
                color=discord.Color.green() if total_deleted > 0 else discord.Color.blue(),
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
