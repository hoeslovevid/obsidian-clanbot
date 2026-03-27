"""Database backup and export commands."""
import discord
from discord import app_commands
import os
import shutil
import json
from datetime import datetime, timezone
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


async def create_backup(guild_id: Optional[int] = None) -> str:
    """Create a backup of the database. Returns the backup file path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    if guild_id:
        backup_dir = f"backups/guild_{guild_id}"
        backup_filename = f"backup_{guild_id}_{timestamp}.db"
    else:
        backup_dir = "backups"
        backup_filename = f"backup_{timestamp}.db"
    
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, backup_filename)
    
    # Copy database file
    shutil.copy2(DB_PATH, backup_path)
    
    return backup_path


async def export_user_data(guild_id: int, user_id: int) -> dict:
    """Export all user data for GDPR compliance."""
    data = {
        "user_id": user_id,
        "guild_id": guild_id,
        "exported_at": now_utc().isoformat(),
        "data": {}
    }
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Economy data
        cur = await db.execute("""
            SELECT balance, total_earned FROM user_balances
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["data"]["economy"] = {
                "balance": row[0],
                "total_earned": row[1]
            }
        
        # XP data
        cur = await db.execute("""
            SELECT xp, level, total_xp FROM user_xp
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["data"]["xp"] = {
                "xp": row[0],
                "level": row[1],
                "total_xp": row[2]
            }
        
        # Activity stats
        cur = await db.execute("""
            SELECT * FROM activity_stats
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["data"]["activity"] = {
                "messages_sent": row[2],
                "events_attended": row[3],
                "voice_minutes": row[4],
                "commands_used": row[5],
                "last_activity_date": row[6],
                "weekly_score": row[7],
                "monthly_score": row[8]
            }
        
        # Achievements
        cur = await db.execute("""
            SELECT achievement_id, unlocked_at FROM achievements
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["achievements"] = [{"id": row[0], "unlocked_at": row[1]} for row in await cur.fetchall()]
        
        # Warnings
        cur = await db.execute("""
            SELECT id, moderator_id, reason, created_at FROM warnings
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["warnings"] = [
            {"id": row[0], "moderator_id": row[1], "reason": row[2], "created_at": row[3]}
            for row in await cur.fetchall()
        ]
        
        # Applications
        cur = await db.execute("""
            SELECT id, status, created_at, submitted_at FROM applications
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["applications"] = [
            {"id": row[0], "status": row[1], "created_at": row[2], "submitted_at": row[3]}
            for row in await cur.fetchall()
        ]
        
        # Suggestions
        cur = await db.execute("""
            SELECT id, suggestion_text, status, created_at FROM suggestions
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["suggestions"] = [
            {"id": row[0], "text": row[1], "status": row[2], "created_at": row[3]}
            for row in await cur.fetchall()
        ]
        
        # Tickets
        cur = await db.execute("""
            SELECT ticket_id, subject, status, created_at, closed_at FROM tickets
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["tickets"] = [
            {"id": row[0], "subject": row[1], "status": row[2], "created_at": row[3], "closed_at": row[4]}
            for row in await cur.fetchall()
        ]
        
        # Complaints
        cur = await db.execute("""
            SELECT case_id, category, status, created_at FROM complaints
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        data["data"]["complaints"] = [
            {"case_id": row[0], "category": row[1], "status": row[2], "created_at": row[3]}
            for row in await cur.fetchall()
        ]
    
    return data


def setup(bot, group=None):
    """Register backup commands."""
    # Backup command (mods only)
    backup_decorator = group.command(name="backup", description="Create a database backup (moderators only).") if group else bot.tree.command(name="backup", description="Create a database backup (moderators only).")
    
    @backup_decorator
    async def backup_command(interaction: discord.Interaction):
        """Create a database backup."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can create backups.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Backups are created per server — use this in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        
        try:
            backup_path = await create_backup(interaction.guild.id)
            file_size = os.path.getsize(backup_path) / 1024  # KB
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Backup Created",
                    f"Database backup created successfully.\n\n"
                    f"**File:** `{os.path.basename(backup_path)}`\n"
                    f"**Size:** {file_size:.2f} KB\n"
                    f"**Location:** `{backup_path}`",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Backup Failed",
                    f"Failed to create backup: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
    
    # Export user data command
    export_decorator = group.command(name="export_data", description="Export your user data (GDPR compliance).") if group else bot.tree.command(name="export_data", description="Export your user data (GDPR compliance).")
    
    @export_decorator
    @app_commands.describe(user="User to export data for (mods only, defaults to yourself)")
    async def export_data(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Export user data."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Data export is tied to a server — use this in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        target_user = user or interaction.user
        is_moderator = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # Users can only export their own data unless they're a mod
        if target_user.id != interaction.user.id and not is_moderator:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "You can only export your own data.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        try:
            data = await export_user_data(interaction.guild.id, target_user.id)
            
            # Create JSON file
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"user_data_{target_user.id}_{timestamp}.json"
            filepath = os.path.join("exports", filename)
            os.makedirs("exports", exist_ok=True)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            file_size = os.path.getsize(filepath) / 1024  # KB
            
            # Send file
            file_obj = discord.File(filepath, filename=filename)
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Data Exported",
                    f"User data exported successfully.\n\n"
                    f"**User:** {target_user.mention}\n"
                    f"**File Size:** {file_size:.2f} KB\n"
                    f"**Exported At:** {data['exported_at']}",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                file=file_obj,
                ephemeral=True
            )
            
            # Clean up file after sending (optional - you might want to keep it)
            # os.remove(filepath)
            
        except Exception as e:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Export Failed",
                    f"Failed to export data: {str(e)}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
