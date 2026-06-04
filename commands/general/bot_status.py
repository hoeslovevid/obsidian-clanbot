"""Bot health monitoring and diagnostics command."""
import discord
from discord import app_commands
import os
import platform
from datetime import datetime, timezone

from core.utils import obsidian_embed, is_mod
from core.config import BOT_VERSION
from core.command_tree_stats import collect_command_tree_stats
from core.error_handling import RECENT_ERRORS
from database import DB_PATH, now_utc
import aiosqlite

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


async def check_database_health() -> dict:
    """Check database health and integrity."""
    health = {
        "status": "healthy",
        "size_mb": 0,
        "table_count": 0,
        "issues": []
    }
    
    try:
        # Check if database exists
        if not os.path.exists(DB_PATH):
            health["status"] = "error"
            health["issues"].append("Database file not found")
            return health
        
        # Get file size
        health["size_mb"] = os.path.getsize(DB_PATH) / (1024 * 1024)
        
        # Check database integrity
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            # Get table count
            cur = await db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = await cur.fetchall()
            health["table_count"] = len(tables)
            
            # Check integrity
            try:
                cur = await db.execute("PRAGMA integrity_check")
                result = await cur.fetchone()
                if result and result[0] != "ok":
                    health["status"] = "warning"
                    health["issues"].append(f"Integrity check: {result[0]}")
            except Exception as e:
                health["status"] = "warning"
                health["issues"].append(f"Integrity check failed: {str(e)}")
            
            # Check for locked database
            try:
                await db.execute("SELECT 1")
            except Exception as e:
                if "locked" in str(e).lower():
                    health["status"] = "warning"
                    health["issues"].append("Database may be locked")
            
            # Check table counts (sample a few important tables)
            important_tables = [
                "user_balances", "user_xp", "applications", 
                "complaints", "events", "activity_stats"
            ]
            for table in important_tables:
                try:
                    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                    count = (await cur.fetchone())[0]
                    health[f"{table}_count"] = count
                except Exception:
                    pass  # Table might not exist, that's okay
    
    except Exception as e:
        health["status"] = "error"
        health["issues"].append(f"Database check failed: {str(e)}")
    
    return health


def setup(bot, group=None):
    """Register bot status command."""
    command_decorator = group.command(name="bot_status", description="Check bot health and diagnostics.") if group else bot.tree.command(name="bot_status", description="Check bot health and diagnostics.")
    
    @command_decorator
    async def bot_status(interaction: discord.Interaction):
        """Display bot health status and diagnostics."""
        await interaction.response.defer(ephemeral=True)
        
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # Basic bot info
        if hasattr(bot, 'start_time'):
            uptime = now_utc() - bot.start_time
            uptime_str = str(uptime).split('.')[0]
        else:
            uptime_str = "Unknown"
        
        # System info
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                memory_mb = process.memory_info().rss / (1024 * 1024)
                cpu_percent = process.cpu_percent(interval=0.1)
            except Exception:
                memory_mb = 0
                cpu_percent = 0
        else:
            memory_mb = 0
            cpu_percent = 0
        
        # Database health
        db_health = await check_database_health()
        
        # Bot latency
        latency_ms = round(bot.latency * 1000, 2)
        tree_stats = collect_command_tree_stats(bot)
        command_count = tree_stats.top_level + tree_stats.grouped_subcommands
        error_count = len(RECENT_ERRORS)
        
        # Guild and user counts (single snapshot so list and count stay in sync)
        guild_list = list(bot.guilds)
        guild_count = len(guild_list)
        user_count = len(set(member.id for guild in guild_list for member in guild.members))
        
        # Build embed
        fields = []
        
        # System Status
        status_emoji = "✅" if db_health["status"] == "healthy" else "⚠️" if db_health["status"] == "warning" else "❌"
        fields.append((
            f"{status_emoji} System Status",
            f"**Status:** {db_health['status'].title()}\n"
            f"**Version:** {BOT_VERSION}\n"
            f"**Uptime:** {uptime_str}\n"
            f"**Latency:** {latency_ms}ms\n"
            f"**Recent errors:** {error_count}\n"
            f"**Memory:** {memory_mb:.1f} MB\n"
            f"**CPU:** {cpu_percent:.1f}%",
            True
        ))
        
        # Database Status
        db_emoji = "✅" if db_health["status"] == "healthy" else "⚠️"
        db_status_text = f"**Status:** {db_health['status'].title()}\n"
        db_status_text += f"**Size:** {db_health['size_mb']:.2f} MB\n"
        db_status_text += f"**Tables:** {db_health['table_count']}\n"
        
        if db_health.get("user_balances_count") is not None:
            db_status_text += f"**Users (economy):** {db_health.get('user_balances_count', 0):,}\n"
        if db_health.get("applications_count") is not None:
            db_status_text += f"**Applications:** {db_health.get('applications_count', 0):,}\n"
        if db_health.get("complaints_count") is not None:
            db_status_text += f"**Complaints:** {db_health.get('complaints_count', 0):,}"
        
        if db_health["issues"]:
            db_status_text += f"\n\n**⚠️ Issues:**\n" + "\n".join(f"• {issue}" for issue in db_health["issues"][:3])
        
        fields.append(("💾 Database Status", db_status_text, True))
        
        # Bot Statistics (use guild_list snapshot so suffix count matches displayed list)
        guilds_shown = guild_list[:15]
        servers_text = "\n".join(f"• {g.name} (`{g.id}`)" for g in guilds_shown)
        if guild_count > 15:
            servers_text += f"\n_... and {guild_count - 15} more_"
        if not servers_text:
            servers_text = "_None_"
        fields.append((
            "📊 Bot Statistics",
            f"**Guilds:** {guild_count:,}\n"
            f"**Users:** {user_count:,}\n"
            f"**Commands:** {command_count:,} ({tree_stats.top_level} top-level)\n"
            f"**Platform:** {platform.system()}",
            True
        ))
        fields.append((
            "🖥️ Servers",
            servers_text,
            False
        ))
        
        # Additional info for moderators
        if is_user_mod:
            try:
                # Check for recent errors (if you have error logging)
                # This is a placeholder - you'd need to implement error tracking
                fields.append((
                    "🔧 Technical Details",
                    f"**Python:** {platform.python_version()}\n"
                    f"**Discord.py:** {discord.__version__}\n"
                    f"**Database Path:** `{DB_PATH}`",
                    False
                ))
            except Exception:
                pass
        
        embed = obsidian_embed(
            "🤖 Bot Health Status",
            "Current bot health and diagnostic information.",
            color=discord.Color.green() if db_health["status"] == "healthy" else discord.Color.orange(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
