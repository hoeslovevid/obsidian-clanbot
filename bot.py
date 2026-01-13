import os
import re
import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

import aiosqlite  # type: ignore
import aiohttp  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore
from discord.ext import commands, tasks  # type: ignore
from dotenv import load_dotenv  # type: ignore
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True  # Force reconfiguration if already configured
)
logger = logging.getLogger(__name__)

# ============================================================
# Obsidian Clan Bot (Warframe Discord)
# - Join-to-create temporary voice channels in "Temp VCs"
# - Obsidian voice control panels (buttons + modals)
# - Complaints desk (button -> modal -> case embed + staff thread)
# - Mod actions + DM status updates to user
# - Ops events (natural language time parsing, RSVP, reminder)
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError(
        "Missing DISCORD_TOKEN environment variable. "
        "Please set DISCORD_TOKEN in your environment variables or Railway dashboard."
    )

# Optional (faster command sync when set; otherwise global sync)
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")

MOD_ROLE_NAME = os.getenv("MOD_ROLE_NAME", "Obsidian Inheritor")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")

# Temp VC config
TEMP_VC_CATEGORY_ID = int(os.getenv("TEMP_VC_CATEGORY_ID", "0") or "0")
TEMP_VC_CATEGORY_NAME = os.getenv("TEMP_VC_CATEGORY_NAME", "Temp VCs")
CREATE_VC_NAME = os.getenv("CREATE_VC_NAME", "➕ Form Squad")
VOICE_IDLE_DELETE_MINUTES = int(os.getenv("VOICE_IDLE_DELETE_MINUTES", "5"))
VC_CLEANUP_INTERVAL_MINUTES = int(os.getenv("VC_CLEANUP_INTERVAL_MINUTES", "2"))

# Channel names (used if IDs not provided / when AUTO_SETUP makes them)
VOICE_PANEL_CHANNEL_ID = int(os.getenv("VOICE_PANEL_CHANNEL_ID", "0") or "0")
VOICE_PANEL_CHANNEL_NAME = os.getenv("VOICE_PANEL_CHANNEL_NAME", "obsidian-console")

COMPLAINTS_CHANNEL_ID = int(os.getenv("COMPLAINTS_CHANNEL_ID", "0") or "0")
COMPLAINTS_CHANNEL_NAME = os.getenv("COMPLAINTS_CHANNEL_NAME", "inheritor-docket")

COMPLAINTS_LOG_CHANNEL_ID = int(os.getenv("COMPLAINTS_LOG_CHANNEL_ID", "0") or "0")
COMPLAINTS_LOG_CHANNEL_NAME = os.getenv("COMPLAINTS_LOG_CHANNEL_NAME", "docket-ledger")

EVENTS_CHANNEL_ID = int(os.getenv("EVENTS_CHANNEL_ID", "0") or "0")
EVENTS_CHANNEL_NAME = os.getenv("EVENTS_CHANNEL_NAME", "ops-board")

# Economy config
ECONOMY_ENABLED = os.getenv("ECONOMY_ENABLED", "true").lower() == "true"
COINS_PER_MESSAGE = int(os.getenv("COINS_PER_MESSAGE", "5"))
COINS_PER_MINUTE_VOICE = int(os.getenv("COINS_PER_MINUTE_VOICE", "2"))
COINS_DAILY_REWARD = int(os.getenv("COINS_DAILY_REWARD", "100"))
MESSAGE_COOLDOWN_SECONDS = int(os.getenv("MESSAGE_COOLDOWN_SECONDS", "60"))
VOICE_REWARD_INTERVAL_MINUTES = int(os.getenv("VOICE_REWARD_INTERVAL_MINUTES", "1"))
MIN_VOICE_MINUTES_FOR_REWARD = int(os.getenv("MIN_VOICE_MINUTES_FOR_REWARD", "1"))

AUTO_SETUP = os.getenv("AUTO_SETUP", "true").lower() in ("1", "true", "yes", "y", "on")

# Events
EVENT_REMINDER_MINUTES_BEFORE = int(os.getenv("EVENT_REMINDER_MINUTES_BEFORE", "60"))
EVENT_REMINDER_LOOP_MINUTES = int(os.getenv("EVENT_REMINDER_LOOP_MINUTES", "1"))

# Intents
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.voice_states = True


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Import obsidian_embed from utils (after bot is created to avoid circular imports)
from utils import obsidian_embed


def get_mod_role(guild: discord.Guild) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=MOD_ROLE_NAME)


def is_mod(member: discord.Member) -> bool:
    return any(r.name == MOD_ROLE_NAME for r in member.roles)


def parse_time_natural(text: str) -> Optional[datetime]:
    """
    Returns a timezone-aware datetime in UTC, or None.
    Accepts: "tomorrow 8pm", "Jan 15 7:30pm", etc.
    """
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": TIMEZONE,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TO_TIMEZONE": "UTC",
            "PREFER_DATES_FROM": "future",
        },
    )
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_id(text: str) -> Optional[int]:
    m = re.search(r"(\d{15,25})", text or "")
    return int(m.group(1)) if m else None

def display_case_status(status: str) -> str:
    s = (status or "").strip().upper()
    return {
        "OPEN": "Filed",
        "ACKNOWLEDGED": "Reviewed",
        "NEEDS INFO": "Evidence Requested",
        "RESOLVED": "Closed",
        "REJECTED": "Dismissed",
    }.get(s, status.title() if status else "Unknown")


# Global tracking set for modal submissions to prevent duplicates
_processed_modal_submissions = set()

# --------------------- Bot ---------------------
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        # Sync commands: to a single guild for speed if GUILD_ID set, else global.
        # Note: Commands are already loaded via load_all_commands() before bot creation
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                # Don't use copy_global_to to avoid duplicates - just sync guild commands directly
                await self.tree.sync(guild=guild)
                # List all registered commands for verification
                commands_list = [cmd.name for cmd in self.tree.get_commands(guild=guild)]
                print(f"[sync] Synced {len(commands_list)} commands to guild {GUILD_ID}")
                print(f"[sync] Commands: {', '.join(commands_list)}")
            else:
                await self.tree.sync()
                commands_list = [cmd.name for cmd in self.tree.get_commands(guild=None)]
                print(f"[sync] Synced {len(commands_list)} commands globally (may take a while to appear)")
                print(f"[sync] Commands: {', '.join(commands_list)}")
        except Exception as e:
            print(f"[sync] Failed to sync commands: {e}")
            import traceback
            traceback.print_exc()


bot = ClanBot()

# Load commands after bot is created (avoids circular imports)
def load_all_commands():
    """Load all command modules."""
    import importlib
    command_modules = [
        # General commands
        "commands.general.help",
        "commands.general.setup_obsidian",
        "commands.general.setup_docket",
        "commands.general.sync_commands",
        # Event commands
        "commands.events.event_create",
        # Complaint commands
        "commands.complaints.submit_complaint",
        "commands.complaints.request_help",
        # Moderation commands
        "commands.moderation.purge",
        # Economy commands
        "commands.economy.balance",
        "commands.economy.leaderboard",
        "commands.economy.transfer",
        "commands.economy.daily",
        "commands.economy.xp",
        "commands.economy.xpleaderboard",
        "commands.economy.add_coins",
        # Warframe commands
        "commands.warframe.baro",
        "commands.warframe.baro_notify",
        "commands.warframe.lfg",
        "commands.warframe.lfg_list",
        "commands.warframe.cycles",
        "commands.warframe.cycle_notify",
    ]
    
    loaded_count = 0
    for module_name in command_modules:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "setup"):
                module.setup(bot)
                loaded_count += 1
                print(f"[commands] Loaded {module_name}")
            else:
                print(f"[commands] WARNING: {module_name} has no setup() function")
        except Exception as e:
            print(f"[commands] ERROR: Failed to load {module_name}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"[commands] Successfully loaded {loaded_count}/{len(command_modules)} command modules")
    
    # Verify all commands are registered
    all_commands = [cmd.name for cmd in bot.tree.get_commands(guild=None)]
    print(f"[commands] Registered commands: {', '.join(sorted(all_commands))}")

# Load commands BEFORE setup_hook runs
load_all_commands()


# --------------------- DB ---------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_vcs (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_nonempty_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS vc_panels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            details TEXT NOT NULL,
            evidence TEXT,
            status TEXT NOT NULL,
            staff_thread_id INTEGER,
            last_update_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, case_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaint_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            description TEXT NOT NULL,
            role_id INTEGER,
            created_at TEXT NOT NULL,
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            thread_id INTEGER,
            PRIMARY KEY (guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS event_rsvps (
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            PRIMARY KEY (guild_id, message_id, user_id)
        )""")

        # Economy tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_balances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            total_earned INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS economy_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS voice_activity (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            last_reward_at TEXT,
            total_minutes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id, channel_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS message_cooldowns (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_message_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_xp (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            total_xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_claims (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_claim_date TEXT NOT NULL,
            streak_days INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arrival_time TEXT NOT NULL,
            departure_time TEXT NOT NULL,
            location TEXT NOT NULL,
            inventory_json TEXT,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS baro_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            mission_type TEXT NOT NULL,
            player_count INTEGER NOT NULL,
            max_players INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS lfg_rsvps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lfg_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (lfg_id) REFERENCES lfg_posts(id) ON DELETE CASCADE,
            UNIQUE(lfg_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            cetus_enabled INTEGER NOT NULL DEFAULT 0,
            fortuna_enabled INTEGER NOT NULL DEFAULT 0,
            deimos_enabled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS cycle_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            cycle_type TEXT NOT NULL,
            cycle_state TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, cycle_type, cycle_state, notified_at)
        )""")

        await db.commit()


# --------------------- Economy Functions ---------------------
async def get_user_balance(guild_id: int, user_id: int) -> int:
    """Get a user's current balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def add_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None):
    """Add coins to a user's balance and log the transaction."""
    if amount <= 0:
        return
    
    desc = description or ""
    async with aiosqlite.connect(DB_PATH) as db:
        # Insert or update balance
        await db.execute("""
            INSERT INTO user_balances (guild_id, user_id, balance, total_earned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                balance = balance + ?,
                total_earned = total_earned + ?
        """, (guild_id, user_id, amount, amount, amount, amount))
        
        # Log transaction
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, amount, transaction_type, desc, now_utc().isoformat()))
        
        await db.commit()


async def remove_coins(guild_id: int, user_id: int, amount: int, transaction_type: str, description: Optional[str] = None) -> bool:
    """Remove coins from a user's balance. Returns True if successful, False if insufficient balance."""
    if amount <= 0:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Check current balance
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        current_balance = row[0] if row else 0
        
        if current_balance < amount:
            return False
        
        # Update balance
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE guild_id=? AND user_id=?
        """, (amount, guild_id, user_id))
        
        # Log transaction
        desc = description or ""
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, user_id, -amount, transaction_type, desc, now_utc().isoformat()))
        
        await db.commit()
        return True


async def transfer_coins(guild_id: int, from_user_id: int, to_user_id: int, amount: int) -> bool:
    """Transfer coins between users. Returns True if successful."""
    if amount <= 0 or from_user_id == to_user_id:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Check sender balance
        cur = await db.execute(
            "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
            (guild_id, from_user_id),
        )
        row = await cur.fetchone()
        sender_balance = row[0] if row else 0
        
        if sender_balance < amount:
            return False
        
        # Remove from sender
        await db.execute("""
            UPDATE user_balances SET balance = balance - ? WHERE guild_id=? AND user_id=?
        """, (amount, guild_id, from_user_id))
        
        # Add to receiver
        await db.execute("""
            INSERT INTO user_balances (guild_id, user_id, balance, total_earned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = balance + ?
        """, (guild_id, to_user_id, amount, 0, amount))
        
        # Log transactions
        now = now_utc().isoformat()
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, from_user_id, -amount, "TRANSFER_OUT", f"Transferred to user {to_user_id}", now))
        
        await db.execute("""
            INSERT INTO economy_transactions (guild_id, user_id, amount, transaction_type, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guild_id, to_user_id, amount, "TRANSFER_IN", f"Received from user {from_user_id}", now))
        
        await db.commit()
        return True


# --------------------- XP Functions ---------------------
def calculate_level(xp: int, multiplier: int = 100) -> int:
    """Calculate level from XP. Formula: XP = level^2 * multiplier"""
    if xp <= 0:
        return 0
    import math
    level = int(math.sqrt(xp / multiplier))
    return max(0, level)


def xp_for_level(level: int, multiplier: int = 100) -> int:
    """Calculate XP needed for a specific level."""
    return int(level ** 2 * multiplier)


def xp_for_next_level(current_level: int, multiplier: int = 100) -> int:
    """Calculate XP needed to reach the next level."""
    return xp_for_level(current_level + 1, multiplier)


async def get_user_xp(guild_id: int, user_id: int) -> Tuple[int, int, int]:
    """Get a user's XP, level, and total XP. Returns (xp, level, total_xp)."""
    from utils import XP_LEVEL_MULTIPLIER
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            xp, level, total_xp = row
            # Recalculate level in case XP changed
            actual_level = calculate_level(xp, XP_LEVEL_MULTIPLIER)
            if actual_level != level:
                # Update level if it changed
                await db.execute(
                    "UPDATE user_xp SET level=? WHERE guild_id=? AND user_id=?",
                    (actual_level, guild_id, user_id),
                )
                await db.commit()
                return (xp, actual_level, total_xp)
            return (xp, level, total_xp)
        return (0, 0, 0)


async def add_xp(guild_id: int, user_id: int, amount: int, source: str = "ACTIVITY"):
    """Add XP to a user and update their level."""
    from utils import XP_LEVEL_MULTIPLIER
    if amount <= 0:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get current XP
        cur = await db.execute(
            "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        
        if row:
            current_xp, current_level, total_xp = row
            new_xp = current_xp + amount
            new_total_xp = total_xp + amount
        else:
            current_xp = 0
            current_level = 0
            new_xp = amount
            new_total_xp = amount
        
        # Calculate new level
        new_level = calculate_level(new_xp, XP_LEVEL_MULTIPLIER)
        
        # Update or insert
        await db.execute("""
            INSERT INTO user_xp (guild_id, user_id, xp, level, total_xp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = ?,
                level = ?,
                total_xp = ?
        """, (guild_id, user_id, new_xp, new_level, new_total_xp, new_xp, new_level, new_total_xp))
        
        await db.commit()
        
        # Return if user leveled up
        return new_level > current_level


async def get_guild_setting(guild_id: int, key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def set_guild_setting(guild_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guild_settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value),
        )
        await db.commit()


def format_thread_name(case_id: str, user: discord.Member, category: str = "", date_str: Optional[str] = None) -> str:
    """
    Format a thread name for complaint threads.
    Format: "{username} • {date} • {case_id}"
    Discord thread names max at 100 characters.
    """
    # Get username (display_name or name, max 30 chars)
    username = user.display_name or user.name
    if len(username) > 30:
        username = username[:27] + "..."
    
    # Format date (MM/DD or YYYY-MM-DD)
    if date_str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            date_formatted = dt.strftime("%m/%d")
        except Exception:
            date_formatted = ""
    else:
        from datetime import datetime
        date_formatted = datetime.now().strftime("%m/%d")
    
    # Build thread name
    # Format: "{username} • {date} • {case_id}"
    # If category is short, we can include it: "{username} • {category} • {date} • {case_id}"
    if category and len(category) <= 15:
        thread_name = f"{username} • {category} • {date_formatted} • {case_id}"
    else:
        thread_name = f"{username} • {date_formatted} • {case_id}"
    
    # Ensure it doesn't exceed 100 characters (Discord limit)
    if len(thread_name) > 100:
        # Truncate username if needed
        max_username_len = 100 - len(f" • {date_formatted} • {case_id}")
        if max_username_len < 5:
            # If even that's too long, just use case_id
            thread_name = f"{case_id} • {date_formatted}"
        else:
            username = (user.display_name or user.name)[:max_username_len]
            if category and len(category) <= 15:
                thread_name = f"{username} • {category} • {date_formatted} • {case_id}"
            else:
                thread_name = f"{username} • {date_formatted} • {case_id}"
    
    return thread_name[:100]  # Final safety check


# --------------------- Warframe API Functions ---------------------
async def fetch_baro_data() -> Optional[Dict[str, Any]]:
    """Fetch Baro Ki'Teer data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/voidTrader", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching Baro data: {e}")
        return None


async def fetch_cycle_data(cycle_type: str) -> Optional[Dict[str, Any]]:
    """Fetch cycle data from Warframe World State API.
    
    Args:
        cycle_type: One of 'cetus', 'vallis', or 'cambion'
    
    Returns:
        Cycle data dict or None if error
    """
    endpoints = {
        'cetus': 'https://api.warframestat.us/pc/cetusCycle',
        'vallis': 'https://api.warframestat.us/pc/vallisCycle',
        'cambion': 'https://api.warframestat.us/pc/cambionCycle',
    }
    
    if cycle_type not in endpoints:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoints[cycle_type], timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status} for {cycle_type}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching {cycle_type} cycle data: {e}")
        return None


async def get_all_cycles() -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch all cycle data (Cetus, Fortuna, Deimos)."""
    return {
        'cetus': await fetch_cycle_data('cetus'),
        'vallis': await fetch_cycle_data('vallis'),
        'cambion': await fetch_cycle_data('cambion'),
    }


async def get_baro_status() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get current Baro Ki'Teer status.
    Returns (is_active, baro_data)
    """
    data = await fetch_baro_data()
    if not data:
        return (False, None)
    
    # Check if Baro is active
    activation = data.get("activation", "")
    expiry = data.get("expiry", "")
    
    if not activation or not expiry:
        return (False, data)
    
    try:
        # Parse ISO format timestamps
        activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not activation_time or not expiry_time:
            return (False, data)
        
        now = datetime.now(timezone.utc)
        is_active = activation_time <= now <= expiry_time
        return (is_active, data)
    except Exception as e:
        logger.error(f"Error parsing Baro timestamps: {e}")
        return (False, data)


async def check_and_notify_baro_arrival():
    """Check if Baro has arrived and send notifications if needed."""
    is_active, baro_data = await get_baro_status()
    
    if not baro_data:
        return
    
    activation = baro_data.get("activation", "")
    if not activation:
        return
    
    # Check if we've already notified for this visit
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM baro_visits WHERE arrival_time=? AND notified=1",
            (activation,)
        )
        existing = await cur.fetchone()
        
        if existing:
            return  # Already notified
        
        # Check if this visit exists
        cur = await db.execute(
            "SELECT id, notified FROM baro_visits WHERE arrival_time=?",
            (activation,)
        )
        visit = await cur.fetchone()
        
        visit_id = None
        if visit:
            visit_id, notified = visit
            if notified:
                return  # Already notified, exit
        else:
            # Create new visit record
            inventory_json = json.dumps(baro_data.get("inventory", []))
            await db.execute("""
                INSERT INTO baro_visits (arrival_time, departure_time, location, inventory_json, notified, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (
                activation,
                baro_data.get("expiry", ""),
                baro_data.get("location", "Unknown"),
                inventory_json,
                now_utc().isoformat(),
            ))
            await db.commit()
            
            # Get the visit ID
            cur = await db.execute(
                "SELECT id FROM baro_visits WHERE arrival_time=?",
                (activation,)
            )
            visit = await cur.fetchone()
            visit_id = visit[0] if visit else None
        
        # Send notifications to all guilds that have it enabled
        for guild in bot.guilds:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
                    (guild.id,)
                )
                setting = await cur.fetchone()
            
            if not setting or not setting[1]:  # Not enabled or not set
                continue
            
            channel_id = setting[0]
            if not channel_id:
                continue
            
            ch = guild.get_channel(channel_id)
            if not isinstance(ch, discord.TextChannel):
                continue
            
            # Build notification embed
            location = baro_data.get("location", "Unknown")
            expiry = baro_data.get("expiry", "")
            inventory = baro_data.get("inventory", [])
            
            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if expiry_time:
                    time_remaining = expiry_time - datetime.now(timezone.utc)
                    hours = int(time_remaining.total_seconds() // 3600)
                    minutes = int((time_remaining.total_seconds() % 3600) // 60)
                    time_str = f"{hours}h {minutes}m"
                else:
                    time_str = "Unknown"
            except Exception:
                time_str = "Unknown"
            
            desc = f"**Location:** {location}\n"
            desc += f"**Time Remaining:** {time_str}\n\n"
            
            if inventory:
                desc += "**Inventory:**\n"
                for item in inventory[:10]:  # Limit to first 10 items
                    item_name = item.get("item", "Unknown")
                    ducats = item.get("ducats", 0)
                    credits = item.get("credits", 0)
                    desc += f"• {item_name} - {ducats} ducats, {credits:,} credits\n"
                if len(inventory) > 10:
                    desc += f"\n_...and {len(inventory) - 10} more items_"
            else:
                desc += "Inventory not available yet."
            
            embed = obsidian_embed(
                "🛒 Baro Ki'Teer Has Arrived!",
                desc,
                color=discord.Color.gold(),
                client=bot,
            )
            
            try:
                await ch.send(embed=embed)
                
                # Mark as notified
                if visit_id:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE baro_visits SET notified=1 WHERE id=?",
                            (visit_id,)
                        )
                        await db.commit()
            except Exception as e:
                logger.error(f"Error sending Baro notification to {guild.id}: {e}")


async def log_complaint_action(guild: discord.Guild, case_id: str, actor_id: int, action: str, note: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO complaint_actions(guild_id,case_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?,?)",
            (guild.id, case_id, actor_id, action, note, now_utc().isoformat()),
        )
        await db.commit()

    # Optional ledger channel
    ledger_id = await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    if ledger_id:
        ch = guild.get_channel(ledger_id)
        if ch:
            actor = guild.get_member(actor_id)
            desc = f"**Case:** `{case_id}`\n**Action:** {action}\n**By:** {actor.mention if actor else actor_id}"
            if note:
                desc += f"\n**Note:** {note}"
            await ch.send(embed=obsidian_embed("Docket Ledger", desc, color=discord.Color.dark_grey(), client=bot))


# --------------------- Setup helpers ---------------------
async def find_or_create_text_channel(guild: discord.Guild, *, name: str) -> discord.TextChannel:
    existing = discord.utils.get(guild.text_channels, name=name)
    if isinstance(existing, discord.TextChannel):
        return existing
    return await guild.create_text_channel(name=name, reason="Obsidian bot auto-setup")


async def resolve_channel_id(
    guild: discord.Guild,
    setting_key: str,
    env_id: int,
    fallback_name: str,
) -> int:
    """
    Resolve a channel ID in this order:
    1) guild_settings value
    2) env ID (if provided)
    3) find by fallback_name (case-insensitive, partial match)
    4) create if AUTO_SETUP (only if no existing channel found)
    Saves the resolved ID into guild_settings.
    """
    saved = await get_guild_setting(guild.id, setting_key)
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            return ch.id

    if env_id:
        ch = guild.get_channel(env_id)
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            await set_guild_setting(guild.id, setting_key, str(ch.id))
            return ch.id

    # find by exact name match (case-sensitive)
    ch = discord.utils.get(guild.channels, name=fallback_name)
    if ch:
        await set_guild_setting(guild.id, setting_key, str(ch.id))
        return ch.id

    # find by case-insensitive name match (in case moderators created it with different casing)
    fallback_lower = fallback_name.lower()
    for ch in guild.channels:
        if isinstance(ch, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel)):
            if ch.name.lower() == fallback_lower:
                await set_guild_setting(guild.id, setting_key, str(ch.id))
                return ch.id

    # Before creating, check if there's already a channel that might be serving this purpose
    # by checking if any text channel contains key words from the fallback name
    if setting_key in ("voice_panel_channel_id", "complaints_channel_id", "complaints_log_channel_id", "events_channel_id"):
        # Extract key words from fallback_name (e.g., "obsidian-console" -> ["obsidian", "console"])
        # Normalize by replacing hyphens/underscores with spaces, then split
        normalized_fallback = fallback_name.replace("-", " ").replace("_", " ").lower()
        key_words = [word for word in normalized_fallback.split() if len(word) >= 2]  # Lowered threshold to catch "ops"
        
        for ch in guild.text_channels:
            ch_name_lower = ch.name.lower()
            # Normalize channel name the same way (replace hyphens/underscores with spaces for comparison)
            ch_normalized = ch_name_lower.replace("-", " ").replace("_", " ")
            
            # Check if channel name contains ALL key words (e.g., "ops-board" matches "ops board" or "ops-board" or "board-ops")
            # This is more strict than matching any single keyword
            if key_words and all(word in ch_normalized for word in key_words):
                # Found a potential match - save it and return
                logger.info(f"Found existing channel '{ch.name}' for {setting_key} (matched keywords: {key_words}, fallback: '{fallback_name}')")
                await set_guild_setting(guild.id, setting_key, str(ch.id))
                return ch.id
        
        # Additional fallback: for events channel, also check for common variations
        if setting_key == "events_channel_id":
            # Check for common event-related channel names
            event_keywords = ["event", "ops", "operation", "mission", "raid"]
            for ch in guild.text_channels:
                ch_name_lower = ch.name.lower()
                ch_normalized = ch_name_lower.replace("-", " ").replace("_", " ")
                # Check if channel name contains "ops" or "event" or similar
                if any(keyword in ch_normalized for keyword in event_keywords):
                    logger.info(f"Found potential events channel '{ch.name}' for {setting_key} (matched event keywords)")
                    await set_guild_setting(guild.id, setting_key, str(ch.id))
                    return ch.id

    if not AUTO_SETUP:
        return 0

    # create missing text channels only (as last resort)
    if setting_key in ("voice_panel_channel_id", "complaints_channel_id", "complaints_log_channel_id", "events_channel_id"):
        created = await find_or_create_text_channel(guild, name=fallback_name)
        await set_guild_setting(guild.id, setting_key, str(created.id))
        return created.id

    return 0


async def resolve_temp_vc_category(guild: discord.Guild) -> discord.CategoryChannel:
    if TEMP_VC_CATEGORY_ID:
        cat = guild.get_channel(TEMP_VC_CATEGORY_ID)
        if isinstance(cat, discord.CategoryChannel):
            return cat

    cat = discord.utils.get(guild.categories, name=TEMP_VC_CATEGORY_NAME)
    if isinstance(cat, discord.CategoryChannel):
        return cat

    if not AUTO_SETUP:
        raise RuntimeError("Temp VC category not found. Set TEMP_VC_CATEGORY_ID or TEMP_VC_CATEGORY_NAME.")
    return await guild.create_category(name=TEMP_VC_CATEGORY_NAME, reason="Obsidian bot auto-setup")


async def ensure_join_to_create_channel(guild: discord.Guild) -> int:
    """
    Ensures the join-to-create trigger voice channel exists inside the Temp VCs category.
    Saves it into guild_settings: create_vc_channel_id
    """
    saved = await get_guild_setting(guild.id, "create_vc_channel_id")
    if saved and saved.isdigit():
        ch = guild.get_channel(int(saved))
        if isinstance(ch, discord.VoiceChannel):
            return ch.id

    category = await resolve_temp_vc_category(guild)

    existing = discord.utils.get(category.voice_channels, name=CREATE_VC_NAME)
    if isinstance(existing, discord.VoiceChannel):
        await set_guild_setting(guild.id, "create_vc_channel_id", str(existing.id))
        return existing.id

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
    }
    vc = await guild.create_voice_channel(
        name=CREATE_VC_NAME,
        category=category,
        overwrites=overwrites,
        reason="Auto-created join-to-create channel on bot install",
    )
    await set_guild_setting(guild.id, "create_vc_channel_id", str(vc.id))
    return vc.id


async def ensure_core_channels(guild: discord.Guild):
    # Create / resolve core text channels if AUTO_SETUP enabled or IDs set.
    await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
    await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)


# --------------------- Voice panel views ---------------------
class RenameVCModal(discord.ui.Modal, title="Recalibrate Comms Node"):  # type: ignore
    new_name = discord.ui.TextInput(label="New designation", max_length=80)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        await vc.edit(name=str(self.new_name), reason="Obsidian VC rename")
        await interaction.response.send_message("Renamed.", ephemeral=True)


class InviteModal(discord.ui.Modal, title="Grant Access"):  # type: ignore
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        ow = overwrites.get(member, discord.PermissionOverwrite())
        ow.view_channel = True
        ow.connect = True
        overwrites[member] = ow
        await vc.edit(overwrites=overwrites, reason="Obsidian VC invite")
        await interaction.response.send_message(f"Invited {member.mention}.", ephemeral=True)


class RemoveAccessModal(discord.ui.Modal, title="Revoke Access"):  # type: ignore
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        if member in overwrites:
            del overwrites[member]
            await vc.edit(overwrites=overwrites, reason="Obsidian VC remove access")
        await interaction.response.send_message(f"Access removed for {member.mention}.", ephemeral=True)


class TransferOwnerModal(discord.ui.Modal, title="Pass Command"):  # type: ignore
    target = discord.ui.TextInput(label="New owner (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        new_owner_id = extract_id(str(self.target))
        if not new_owner_id:
            return await interaction.response.send_message("Couldn’t read that user. Use @mention or ID.", ephemeral=True)

        new_owner = interaction.guild.get_member(new_owner_id)
        if not new_owner:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        # Only current owner or mods can transfer
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?", (interaction.guild.id, vc.id))
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Owner record missing.", ephemeral=True)

        current_owner_id = int(row[0])
        actor = interaction.user
        if not isinstance(actor, discord.Member):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        if not (is_mod(actor) or actor.id == current_owner_id):
            return await interaction.response.send_message("Only the owner (or Obsidian Inheritor) can transfer.", ephemeral=True)

        overwrites = vc.overwrites

        old_owner = interaction.guild.get_member(current_owner_id)
        if old_owner:
            ow = overwrites.get(old_owner, discord.PermissionOverwrite())
            ow.manage_channels = False
            ow.move_members = False
            ow.mute_members = False
            ow.deafen_members = False
            overwrites[old_owner] = ow

        ow2 = overwrites.get(new_owner, discord.PermissionOverwrite())
        ow2.view_channel = True
        ow2.connect = True
        ow2.manage_channels = True
        ow2.move_members = True
        ow2.mute_members = True
        ow2.deafen_members = True
        overwrites[new_owner] = ow2

        mod_role = get_mod_role(interaction.guild)
        if mod_role:
            m = overwrites.get(mod_role, discord.PermissionOverwrite())
            m.view_channel = True
            m.connect = True
            overwrites[mod_role] = m

        await vc.edit(overwrites=overwrites, reason="Obsidian transfer ownership")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_vcs SET owner_id=? WHERE guild_id=? AND channel_id=?",
                (new_owner.id, interaction.guild.id, vc.id),
            )
            await db.commit()

        await interaction.response.send_message(f"Ownership transferred to {new_owner.mention}.", ephemeral=True)


class SetLimitSelect(discord.ui.Select):
    def __init__(self, vc_id: int):
        options = [
            discord.SelectOption(label="No limit", value="0"),
            discord.SelectOption(label="2", value="2"),
            discord.SelectOption(label="3", value="3"),
            discord.SelectOption(label="4", value="4"),
            discord.SelectOption(label="6", value="6"),
            discord.SelectOption(label="8", value="8"),
            discord.SelectOption(label="10", value="10"),
            discord.SelectOption(label="12", value="12"),
        ]
        super().__init__(
            placeholder="Set cell capacity…",
            options=options,
            custom_id=f"vc:{vc_id}:setlimit",
        )
        self.vc_id = vc_id

    async def callback(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        try:
            limit = int(self.values[0])
        except ValueError:
            return await interaction.response.send_message("Invalid limit.", ephemeral=True)

        await vc.edit(user_limit=limit, reason="Obsidian VC limit")
        await interaction.response.send_message("Limit updated.", ephemeral=True)


class SetLimitView(discord.ui.View):
    def __init__(self, vc_id: int):
        super().__init__(timeout=120)
        self.add_item(SetLimitSelect(vc_id))


class VCPanelView(discord.ui.View):
    """
    Persistent view per VC (custom_ids include vc_id to avoid collisions).
    We re-register these views on startup for existing temp VCs in the DB.
    """

    def __init__(self, vc_id: int):
        super().__init__(timeout=None)
        self.vc_id = vc_id

        self.add_item(discord.ui.Button(label="Recalibrate", style=discord.ButtonStyle.primary, emoji="✒️", custom_id=f"vc:{vc_id}:rename"))
        self.add_item(discord.ui.Button(label="Capacity", style=discord.ButtonStyle.secondary, emoji="👥", custom_id=f"vc:{vc_id}:limit"))
        self.add_item(discord.ui.Button(label="Seal", style=discord.ButtonStyle.danger, emoji="🔒", custom_id=f"vc:{vc_id}:lock"))
        self.add_item(discord.ui.Button(label="Unseal", style=discord.ButtonStyle.success, emoji="🔓", custom_id=f"vc:{vc_id}:unlock"))
        self.add_item(discord.ui.Button(label="Cloak", style=discord.ButtonStyle.danger, emoji="🫥", custom_id=f"vc:{vc_id}:hide"))
        self.add_item(discord.ui.Button(label="Reveal", style=discord.ButtonStyle.success, emoji="👁️", custom_id=f"vc:{vc_id}:show"))
        self.add_item(discord.ui.Button(label="Grant", style=discord.ButtonStyle.secondary, emoji="➕", custom_id=f"vc:{vc_id}:invite"))
        self.add_item(discord.ui.Button(label="Revoke", style=discord.ButtonStyle.secondary, emoji="⛓️", custom_id=f"vc:{vc_id}:remove"))
        self.add_item(discord.ui.Button(label="Pass Command", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id=f"vc:{vc_id}:transfer"))
        self.add_item(discord.ui.Button(label="Dissolve", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id=f"vc:{vc_id}:disband"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only owner or mods can use most controls
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if is_mod(member):
            return True

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, self.vc_id),
            )
            row = await cur.fetchone()
        return bool(row and int(row[0]) == member.id)

    async def on_timeout(self):
        return


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    panel_ch_id = await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
    if not panel_ch_id:
        return
    panel_ch = guild.get_channel(panel_ch_id)
    if not isinstance(panel_ch, discord.TextChannel):
        return

    embed = obsidian_embed(
        "Obsidian Dojo • Cell Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner.mention}\n\n"
        "Configure your cell channel using the controls below.\n"
        "_Obsidian Inheritors retain oversight._",
        color=discord.Color.dark_grey(),
        client=bot,
    )
    view = VCPanelView(vc.id)
    msg = await panel_ch.send(embed=embed, view=view)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO vc_panels(guild_id, channel_id, message_id) VALUES(?,?,?)",
            (guild.id, vc.id, msg.id),
        )
        await db.commit()

    # Register persistent view (so buttons keep working after restart)
    bot.add_view(view)


async def delete_vc_panel_message(guild: discord.Guild, vc_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT message_id FROM vc_panels WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        row = await cur.fetchone()
        if row:
            msg_id = int(row[0])
            await db.execute("DELETE FROM vc_panels WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
            await db.commit()
        else:
            msg_id = 0

    if msg_id:
        ch_id = await resolve_channel_id(guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME)
        ch = guild.get_channel(ch_id) if ch_id else None
        if isinstance(ch, discord.TextChannel):
            # Type narrowing: ch is now guaranteed to be discord.TextChannel
            text_ch: discord.TextChannel = ch  # type: ignore
            try:
                msg = await text_ch.fetch_message(msg_id)
                if msg:
                    await msg.delete()
            except Exception:
                pass


async def delete_temp_vc_and_panel(guild: discord.Guild, vc_id: int, *, reason: str):
    vc = guild.get_channel(vc_id)
    if isinstance(vc, discord.VoiceChannel):
        try:
            await vc.delete(reason=reason)
        except Exception:
            pass

    await delete_vc_panel_message(guild, vc_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM temp_vcs WHERE guild_id=? AND channel_id=?", (guild.id, vc_id))
        await db.commit()


# --------------------- Complaints ---------------------
class ComplaintModal(discord.ui.Modal, title="Obsidian Docket Submission"):  # type: ignore
    def __init__(self):
        super().__init__(timeout=300, custom_id="complaint_modal")
        
        self.category = discord.ui.TextInput(
            label="Category", 
            placeholder="harassment / trade / voice conduct / etc.", 
            max_length=60,
            custom_id="category"
        )
        self.details = discord.ui.TextInput(
            label="Details", 
            style=discord.TextStyle.paragraph, 
            max_length=1000,
            custom_id="details"
        )
        self.evidence = discord.ui.TextInput(
            label="Evidence (optional link)", 
            required=False, 
            max_length=200,
            custom_id="evidence"
        )
        
        self.add_item(self.category)
        self.add_item(self.details)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        # This method defers the interaction to prevent expiration, but actual processing
        # is handled by the on_interaction handler for persistence after bot restarts.
        # We defer unconditionally (if possible) - on_interaction will check is_done() before deferring
        logger.info(f"[modal] ComplaintModal.on_submit: Attempting to defer (on_interaction will process)")
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info(f"[modal] ComplaintModal.on_submit: Successfully deferred")
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
            # Interaction already handled or expired - on_interaction may have gotten it first
            logger.info(f"[modal] ComplaintModal.on_submit: Could not defer: {e}")
        # Don't process here - let on_interaction handle it
        return
        
        guild = interaction.guild
        # Generate unique case_id with retry logic
        created = now_utc()
        max_retries = 10
        case_id = None
        
        for attempt in range(max_retries):
            # Use microseconds for better uniqueness, plus random component
            timestamp_part = int(created.timestamp() * 1000000)  # microseconds
            random_part = random.randint(1000, 9999)
            user_part = interaction.user.id % 10000
            case_id = f"OBS-{timestamp_part}-{user_part}-{random_part}"
            
            # Check if this case_id already exists
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                    (guild.id, case_id)
                )
                exists = await cur.fetchone()
            
            if not exists:
                break  # Unique case_id found
            
            # If we've exhausted retries, use a more unique approach
            if attempt == max_retries - 1:
                # Fallback: use full timestamp with nanoseconds simulation
                import time
                case_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"
        
        created_iso = created.isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    guild.id,
                    case_id,
                    interaction.user.id,
                    created_iso,
                    str(self.category),
                    str(self.details),
                    str(self.evidence),
                    "OPEN",
                    None,
                    created_iso,
                ),
            )
            await db.commit()

        complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
        ch = guild.get_channel(complaints_id) if complaints_id else None
        if not isinstance(ch, discord.TextChannel):
            # Use followup since we already deferred
            await interaction.followup.send(
                "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                ephemeral=True,
            )
            _processed_modal_submissions.discard(interaction_key)
            return

        mod_role = get_mod_role(guild)
        mention = mod_role.mention if mod_role else f"@{MOD_ROLE_NAME}"

        desc = f"**Category:** {self.category}\n\n**Details:**\n{self.details}"
        if str(self.evidence).strip():
            desc += f"\n\n**Evidence:** {self.evidence}"

        embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red(), client=bot)
        embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

        view = ComplaintModView(case_id)
        msg = await ch.send(content=mention, embed=embed, view=view)
        bot.add_view(view)

        # Thread for staff discussion (tries private first; falls back)
        thread_id = None
        thread_name = format_thread_name(case_id, interaction.user, str(self.category), created_iso)
        try:
            thread = await ch.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Private staff thread for complaint",
            )
            thread_id = thread.id
            if mod_role:
                try:
                    await thread.add_user(interaction.user)  # Might fail; ignore
                except Exception:
                    pass
        except Exception:
            try:
                thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                thread_id = thread.id
            except Exception:
                thread = None

        if thread_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                    (thread_id, guild.id, case_id),
                )
                await db.commit()
            try:
                await thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps.", client=bot))
            except Exception:
                pass

        await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

        # Use followup since we already deferred
        await interaction.followup.send(
            embed=obsidian_embed(
                "Docket Sealed",
                f"Your docket entry has been sealed as **`{case_id}`**.\nYou'll receive DM docket updates as it progresses.",
                color=discord.Color.green(),
                client=bot,
            ),
            ephemeral=True,
        )


class ComplaintPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Seal a Report",
                style=discord.ButtonStyle.danger,
                emoji="🩸",
                custom_id="complaints:open",
            )
        )


class RequestInfoModal(discord.ui.Modal, title="Request Evidence"):  # type: ignore
    def __init__(self, case_id: str):
        super().__init__(timeout=300, custom_id=f"request_info_{case_id}")
        self.case_id = case_id
        
        self.question = discord.ui.TextInput(
            label="Question to ask the user", 
            style=discord.TextStyle.paragraph, 
            max_length=800,
            custom_id="question"
        )
        self.add_item(self.question)

    async def on_submit(self, interaction: discord.Interaction):
        # This method defers the interaction to prevent expiration, but actual processing
        # is handled by the on_interaction handler for persistence after bot restarts.
        # We defer unconditionally (if possible) - on_interaction will check is_done() before deferring
        logger.info(f"[modal] RequestInfoModal.on_submit: Attempting to defer (on_interaction will process)")
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info(f"[modal] RequestInfoModal.on_submit: Successfully deferred")
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
            # Interaction already handled or expired - on_interaction may have gotten it first
            logger.info(f"[modal] RequestInfoModal.on_submit: Could not defer: {e}")
        # Don't process here - let on_interaction handle it
        return


class ComplaintModView(discord.ui.View):
    """
    Persistent per case (custom_ids include case_id).
    We re-register for OPEN/ACK/NEEDS INFO cases on startup.
    """

    def __init__(self, case_id: str):
        super().__init__(timeout=None)
        self.case_id = case_id

        self.add_item(discord.ui.Button(label="Mark Reviewed", style=discord.ButtonStyle.primary, emoji="✅", custom_id=f"complaints:{case_id}:ack"))
        self.add_item(discord.ui.Button(label="Close Docket", style=discord.ButtonStyle.success, emoji="🔒", custom_id=f"complaints:{case_id}:resolve"))
        self.add_item(discord.ui.Button(label="Dismiss", style=discord.ButtonStyle.secondary, emoji="❌", custom_id=f"complaints:{case_id}:reject"))
        self.add_item(discord.ui.Button(label="Request Evidence", style=discord.ButtonStyle.danger, emoji="❗", custom_id=f"complaints:{case_id}:needinfo"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_mod(member)

    async def dm_user(self, guild: discord.Guild, user_id: int, status: str):
        user = guild.get_member(user_id) or await bot.fetch_user(user_id)
        if not user:
            return
        try:
            e = obsidian_embed(f"Docket Update • {self.case_id}", f"Status: **{display_case_status(status)}**", client=bot)
            await user.send(embed=e)
        except discord.Forbidden:
            pass

    async def set_status(self, interaction: discord.Interaction, status: str, *, dm_override: bool = True) -> Optional[int]:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, self.case_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            user_id = int(row[0])

            await db.execute(
                "UPDATE complaints SET status=?, last_update_at=? WHERE guild_id=? AND case_id=?",
                (status, now_utc().isoformat(), interaction.guild.id, self.case_id),
            )
            await db.commit()

        if dm_override:
            await self.dm_user(interaction.guild, user_id, status)

        await log_complaint_action(interaction.guild, self.case_id, interaction.user.id, f"STATUS:{status}")
        return user_id


# --------------------- Events ---------------------
class RSVPView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Going", style=discord.ButtonStyle.success, emoji="✅", custom_id="events:rsvp:going"))
        self.add_item(discord.ui.Button(label="Maybe", style=discord.ButtonStyle.primary, emoji="❔", custom_id="events:rsvp:maybe"))
        self.add_item(discord.ui.Button(label="Can't", style=discord.ButtonStyle.danger, emoji="❌", custom_id="events:rsvp:no"))

    async def _set_rsvp(self, interaction: discord.Interaction, response: str):
        guild_id = interaction.guild.id
        msg_id = interaction.message.id

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO event_rsvps(guild_id,message_id,user_id,response) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id,message_id,user_id) DO UPDATE SET response=excluded.response",
                (guild_id, msg_id, interaction.user.id, response),
            )
            await db.commit()

            cur = await db.execute(
                "SELECT response, COUNT(*) FROM event_rsvps WHERE guild_id=? AND message_id=? GROUP BY response",
                (guild_id, msg_id),
            )
            rows = await cur.fetchall()

        counts = {"GOING": 0, "MAYBE": 0, "NO": 0}
        for r, c in rows:
            counts[str(r)] = int(c)

        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"✅ {counts['GOING']}  |  ❔ {counts['MAYBE']}  |  ❌ {counts['NO']}")
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("RSVP recorded.", ephemeral=True)


# --------------------- Slash Commands ---------------------
# Commands are now loaded from commands/ folder via load_all_commands()


# --------------------- Economy Event Handlers ---------------------
@bot.event
async def on_message(message: discord.Message):
    """Award coins for text messages (with cooldown)."""
    # Ignore bot messages and DMs
    if message.author.bot or not message.guild:
        return
    
    # Check if economy is enabled
    if not ECONOMY_ENABLED:
        return
    
    # Ignore commands (they're handled separately)
    if message.content.startswith("!"):
        return
    
    # Check cooldown
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT last_message_at FROM message_cooldowns WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()
        
        if row:
            last_message_at = datetime.fromisoformat(row[0])
            time_since = (now_utc() - last_message_at).total_seconds()
            if time_since < MESSAGE_COOLDOWN_SECONDS:
                return  # Still on cooldown
        
        # Update cooldown
        await db.execute("""
            INSERT INTO message_cooldowns (guild_id, user_id, last_message_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET last_message_at=?
        """, (message.guild.id, message.author.id, now_utc().isoformat(), now_utc().isoformat()))
        await db.commit()
    
    # Award coins
    await add_coins(
        message.guild.id,
        message.author.id,
        COINS_PER_MESSAGE,
        "MESSAGE",
        f"Message in #{message.channel.name}",
    )
    
    # Award XP (if enabled)
    from utils import XP_ENABLED, XP_PER_MESSAGE
    if XP_ENABLED:
        leveled_up = await add_xp(
            message.guild.id,
            message.author.id,
            XP_PER_MESSAGE,
            "MESSAGE",
        )
        if leveled_up:
            # User leveled up! Could send a notification here if desired
            xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
            logger.info(f"User {message.author.id} leveled up to level {level} in guild {message.guild.id}")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Track voice channel activity for economy rewards and handle join-to-create."""
    # Economy voice tracking (if enabled)
    if ECONOMY_ENABLED:
        now = now_utc()
        
        # User left a voice channel - remove tracking
        if before.channel and isinstance(before.channel, discord.VoiceChannel):
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "DELETE FROM voice_activity WHERE guild_id=? AND user_id=? AND channel_id=?",
                    (member.guild.id, member.id, before.channel.id),
                )
                await db.commit()
        
        # User joined a voice channel - start tracking (if not muted/deafened)
        if after.channel and isinstance(after.channel, discord.VoiceChannel):
            if not (after.self_mute or after.self_deaf):
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO voice_activity (guild_id, user_id, channel_id, joined_at, last_reward_at, total_minutes)
                        VALUES (?, ?, ?, ?, ?, COALESCE((SELECT total_minutes FROM voice_activity WHERE guild_id=? AND user_id=? AND channel_id=?), 0))
                    """, (member.guild.id, member.id, after.channel.id, now.isoformat(), None, member.guild.id, member.id, after.channel.id))
                    await db.commit()
    
    # Original join-to-create logic
    if not after.channel:
        return

    create_id_s = await get_guild_setting(member.guild.id, "create_vc_channel_id")
    if not (create_id_s and create_id_s.isdigit()):
        return

    create_id = int(create_id_s)
    if after.channel.id != create_id:
        # Track last non-empty times for cleanup
        for ch in (before.channel, after.channel):
            if ch and isinstance(ch, discord.VoiceChannel):
                async with aiosqlite.connect(DB_PATH) as db:
                    # Only track channels we own
                    cur = await db.execute(
                        "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                        (member.guild.id, ch.id),
                    )
                    exists = await cur.fetchone()
                    if exists and len(ch.members) > 0:
                        await db.execute(
                            "UPDATE temp_vcs SET last_nonempty_at=? WHERE guild_id=? AND channel_id=?",
                            (now_utc().isoformat(), member.guild.id, ch.id),
                        )
                        await db.commit()
        return

    guild = member.guild
    category = await resolve_temp_vc_category(guild)
    mod_role = get_mod_role(guild)

    # Create VC
    vc_name = f"{member.display_name} • Obsidian Squad"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
        member: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            manage_channels=True,  # lets them edit it via Discord UI
            move_members=True,
            mute_members=True,
            deafen_members=True,
        ),
    }
    if mod_role:
        overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True, connect=True)

    new_vc = await guild.create_voice_channel(
        name=vc_name,
        category=category,
        overwrites=overwrites,
        reason="Join-to-create Obsidian cell VC",
    )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) VALUES(?,?,?,?,?)",
            (guild.id, new_vc.id, member.id, now_utc().isoformat(), now_utc().isoformat()),
        )
        await db.commit()

    # Move member into new VC
    try:
        await member.move_to(new_vc, reason="Move to created squad VC")
    except discord.Forbidden:
        # Needs Move Members permission
        pass

    # Post control panel
    try:
        await post_vc_panel(guild, new_vc, member)
    except Exception:
        pass


# --------------------- Component Router ---------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    """
    We route button/select/modal interactions here so persistent views continue to work after restart.
    Application commands (slash commands) are handled automatically by discord.py.
    """
    # CRITICAL: Let discord.py handle application commands (slash commands) automatically
    # Do NOT process them here - discord.py's command tree handles them
    if interaction.type == discord.InteractionType.application_command:
        # Do nothing - let discord.py's built-in handler process it
        return
    
    # Handle modal submissions
    if interaction.type == discord.InteractionType.modal_submit:
        cid = interaction.data.get("custom_id") if interaction.data else None
        
        # Log that we received a modal submission
        logger.info(f"[modal] Received modal submission: {cid} (ID: {interaction.id})")
        
        # Handle RequestInfoModal submissions
        if cid and cid.startswith("request_info_"):
            # Extract case_id from custom_id
            case_id = cid.replace("request_info_", "")
            
            # Check if interaction is already responded to (by on_submit or another handler)
            # If not done, try to defer (but handle race condition where on_submit defers first)
            if not interaction.response.is_done():
                # Need to defer - on_submit didn't catch it (or we got here first)
                logger.info(f"[modal] RequestInfoModal: Interaction not deferred yet, deferring now")
                try:
                    await interaction.response.defer(ephemeral=True)
                    logger.info(f"[modal] RequestInfoModal: Deferred interaction successfully")
                except discord.errors.NotFound as defer_err:
                    # Interaction expired - can't process it
                    logger.warning(f"[modal] RequestInfoModal: Interaction expired (404), cannot process: {defer_err}")
                    return
                except (discord.errors.InteractionResponded, discord.errors.HTTPException) as defer_err:
                    # Interaction already acknowledged by on_submit or another handler
                    logger.info(f"[modal] RequestInfoModal: Could not defer (already acknowledged): {defer_err}")
                    # Proceed with processing - interaction was acknowledged
                    logger.info(f"[modal] RequestInfoModal: Proceeding with processing despite defer error (interaction was acknowledged)")
            else:
                logger.info(f"[modal] RequestInfoModal: Interaction already done (deferred by on_submit), proceeding with processing")
            
            try:
                
                # Extract question from interaction data
                components = interaction.data.get("components", [])
                question_val = ""
                
                for component in components:
                    components_list = component.get("components", [])
                    for comp in components_list:
                        comp_id = comp.get("custom_id", "")
                        value = comp.get("value", "")
                        if comp_id == "question":
                            question_val = value
                
                if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                    await interaction.followup.send("Obsidian Inheritors only.", ephemeral=True)
                    return

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                        (interaction.guild.id, case_id),
                    )
                    row = await cur.fetchone()
                if not row:
                    await interaction.followup.send("Case not found.", ephemeral=True)
                    return

                user_id = int(row[0])

                # Set status, DM user
                await ComplaintModView(case_id).set_status(interaction, "NEEDS INFO", dm_override=False)

                user = interaction.guild.get_member(user_id) or await bot.fetch_user(user_id)
                if user:
                    try:
                        e = obsidian_embed(
                            f"Evidence Requested • {case_id}",
                            f"**Directive from Obsidian Inheritors:**\n{question_val}\n\n"
                            "Respond using:\n"
                            f"**/submit_complaint** (case_id: `{case_id}`)\n\n"
                            "_If your DMs are closed, you may not receive updates._",
                            color=discord.Color.orange(),
                            client=bot,
                        )
                        await user.send(embed=e)
                    except discord.Forbidden:
                        pass

                await log_complaint_action(interaction.guild, case_id, interaction.user.id, "REQUEST_INFO", question_val)
                
                # Send followup since we deferred
                await interaction.followup.send("Requested evidence (DM sent if possible).", ephemeral=True)
            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(f"Error requesting evidence: {e}", ephemeral=True)
                    else:
                        await interaction.response.send_message(f"Error requesting evidence: {e}", ephemeral=True)
                except Exception:
                    pass
            return
        
        if cid == "complaint_modal":
            # Check if already processed (prevent duplicates)
            # Use interaction ID as unique identifier
            interaction_key = f"{interaction.id}:{interaction.user.id}"
            
            # Check if already processed
            if interaction_key in _processed_modal_submissions:
                logger.info(f"[modal] Already processed: {interaction_key}")
                return  # Already processed
            
            # Check if interaction is already responded to (by on_submit or another handler)
            # If not done, try to defer (but handle race condition where on_submit defers first)
            if not interaction.response.is_done():
                # Need to defer - on_submit didn't catch it (or we got here first)
                logger.info(f"[modal] Interaction not deferred yet, deferring now")
                try:
                    await interaction.response.defer(ephemeral=True)
                    logger.info(f"[modal] Deferred interaction successfully: {interaction_key}")
                except discord.errors.NotFound as defer_err:
                    # Interaction expired - can't process it
                    logger.warning(f"[modal] Interaction expired (404), cannot process: {defer_err}")
                    return
                except (discord.errors.InteractionResponded, discord.errors.HTTPException) as defer_err:
                    # Interaction already acknowledged by on_submit or another handler
                    # Check if it's done now - if so, proceed with processing
                    logger.info(f"[modal] Could not defer (already acknowledged): {defer_err}")
                    # Even if is_done() is False, if we got "already acknowledged", 
                    # it means someone else acknowledged it, so proceed with processing
                    # The interaction will be marked as done when we try to use it
                    logger.info(f"[modal] Proceeding with processing despite defer error (interaction was acknowledged)")
                except Exception as defer_err:
                    logger.error(f"[modal] Unexpected error during defer: {defer_err}", exc_info=True)
                    return
            else:
                logger.info(f"[modal] Interaction already done (deferred by on_submit), proceeding with processing")
            
            # Mark as processing immediately
            _processed_modal_submissions.add(interaction_key)
            logger.info(f"[modal] Processing complaint submission: {interaction_key}")
            
            try:
                
                # Extract values from interaction data
                components = interaction.data.get("components", [])
                category_val = ""
                details_val = ""
                evidence_val = ""
                
                for component in components:
                    components_list = component.get("components", [])
                    for comp in components_list:
                        comp_id = comp.get("custom_id", "")
                        value = comp.get("value", "")
                        if comp_id == "category":
                            category_val = value
                        elif comp_id == "details":
                            details_val = value
                        elif comp_id == "evidence":
                            evidence_val = value
                
                # Process complaint submission directly
                guild = interaction.guild
                if not guild:
                    return await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                
                # Generate unique case_id with retry logic
                created = now_utc()
                max_retries = 10
                case_id = None
                
                for attempt in range(max_retries):
                    # Use microseconds for better uniqueness, plus random component
                    timestamp_part = int(created.timestamp() * 1000000)  # microseconds
                    random_part = random.randint(1000, 9999)
                    user_part = interaction.user.id % 10000
                    case_id = f"OBS-{timestamp_part}-{user_part}-{random_part}"
                    
                    # Check if this case_id already exists
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                            (guild.id, case_id)
                        )
                        exists = await cur.fetchone()
                    
                    if not exists:
                        break  # Unique case_id found
                    
                    # If we've exhausted retries, use a more unique approach
                    if attempt == max_retries - 1:
                        # Fallback: use full timestamp with nanoseconds simulation
                        import time
                        case_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"
                
                created_iso = created.isoformat()

                # Check if case already exists before inserting (extra safety check)
                async with aiosqlite.connect(DB_PATH) as db:
                    # Check if this exact submission already exists (same user, same content, within last 5 seconds)
                    check_cur = await db.execute(
                        "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND created_at > datetime('now', '-5 seconds')",
                        (guild.id, interaction.user.id, category_val, details_val)
                    )
                    existing = await check_cur.fetchone()
                    if existing:
                        # Duplicate detected - clean up and return
                        _processed_modal_submissions.discard(interaction_key)
                        await interaction.followup.send("This submission was already processed.", ephemeral=True)
                        return
                    
                    await db.execute(
                        "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            guild.id,
                            case_id,
                            interaction.user.id,
                            created_iso,
                            category_val,
                            details_val,
                            evidence_val,
                            "OPEN",
                            None,
                            created_iso,
                        ),
                    )
                    await db.commit()

                complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
                ch = guild.get_channel(complaints_id) if complaints_id else None
                if not isinstance(ch, discord.TextChannel):
                    return await interaction.followup.send(
                        "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                        ephemeral=True,
                    )

                # Type guard: ensure case_id is not None
                if not case_id:
                    return await interaction.followup.send("Error: Failed to generate case ID.", ephemeral=True)

                # Type narrowing: ch is now guaranteed to be discord.TextChannel
                assert isinstance(ch, discord.TextChannel)

                mod_role = get_mod_role(guild)
                mention = mod_role.mention if mod_role else f"@{MOD_ROLE_NAME}"

                desc = f"**Category:** {category_val}\n\n**Details:**\n{details_val}"
                if evidence_val.strip():
                    desc += f"\n\n**Evidence:** {evidence_val}"

                embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red(), client=bot)
                embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

                view = ComplaintModView(case_id)
                msg = await ch.send(content=mention, embed=embed, view=view)  # type: ignore
                bot.add_view(view)

                # Thread for staff discussion (tries private first; falls back)
                thread_id: Optional[int] = None  # type: ignore
                thread_name = format_thread_name(case_id, interaction.user, category_val, created_iso)
                staff_thread: Optional[discord.Thread] = None  # type: ignore
                try:
                    staff_thread = await ch.create_thread(  # type: ignore
                        name=thread_name,
                        type=discord.ChannelType.private_thread,
                        invitable=False,
                        reason="Private staff thread for complaint",
                    )
                    thread_id = staff_thread.id if staff_thread else None
                    if mod_role and staff_thread:
                        try:
                            await staff_thread.add_user(interaction.user)  # Might fail; ignore
                        except Exception:
                            pass
                except Exception:
                    try:
                        staff_thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                        thread_id = staff_thread.id if staff_thread else None
                    except Exception:
                        staff_thread = None

                if thread_id and staff_thread:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                            (thread_id, guild.id, case_id),
                        )
                        await db.commit()
                    try:
                        await staff_thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps.", client=bot))
                    except Exception:
                        pass

                await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

                await interaction.followup.send(
                    embed=obsidian_embed(
                        "Docket Sealed",
                        f"Your docket entry has been sealed as **`{case_id}`**.\nYou'll receive DM docket updates as it progresses.",
                        color=discord.Color.green(),
                        client=bot,
                    ),
                    ephemeral=True,
                )
                logger.info(f"[modal] Successfully created complaint: {case_id}")
            except Exception as e:
                # Handle errors in modal submission
                logger.error(f"[modal] Error in complaint modal submission: {e}", exc_info=True)
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(f"Error submitting docket: {str(e)}", ephemeral=True)
                    else:
                        try:
                            await interaction.response.send_message(f"Error submitting docket: {str(e)}", ephemeral=True)
                        except (discord.errors.NotFound, discord.errors.InteractionResponded) as err:
                            logger.warning(f"[modal] Could not send error response: {err}")
                except Exception as err:
                    # If we can't send error message, log it
                    logger.error(f"[modal] Could not send error message: {err}", exc_info=True)
            finally:
                # Clean up tracking after a delay (allow time for any duplicate processing to be caught)
                if 'interaction_key' in locals():
                    try:
                        await asyncio.sleep(2)
                        _processed_modal_submissions.discard(interaction_key)
                    except Exception:
                        pass
            return
        
        # For other modals (with auto-generated custom_ids from previous bot sessions),
        # try to extract data from the interaction and process it as a complaint
        # This handles cases where the modal was created before the bot restarted
        logger.info(f"[modal] Unknown modal custom_id: {cid} - attempting to extract as complaint modal")
        
        # Extract modal data - helper function to get values from any modal submission
        def extract_modal_values(interaction_data):
            """Extract text input values from modal interaction data"""
            values = {}
            components = interaction_data.get("components", [])
            for row in components:
                if "components" in row:
                    for component in row["components"]:
                        comp_id = component.get("custom_id", "")
                        comp_value = component.get("value", "")
                        if comp_id:
                            values[comp_id] = comp_value
            return values
        
        # Try to extract complaint data from the modal submission
        try:
            values = extract_modal_values(interaction.data or {})
            
            # Check if this looks like a complaint modal (has category, details fields)
            if "category" in values or "details" in values:
                # This is likely a complaint modal submission - process it
                logger.info(f"[modal] Detected complaint modal from auto-generated ID, extracting values: {list(values.keys())}")
                
                # Process it the same way as complaint_modal (reuse existing handler logic)
                # Import the processing function or inline it here
                interaction_key = f"{interaction.id}:{interaction.user.id}"
                if interaction_key in _processed_modal_submissions:
                    logger.info(f"[modal] Already processed: {interaction_key}")
                    return
                
                _processed_modal_submissions.add(interaction_key)
                
                try:
                    # Defer if not already done
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                    
                    # Extract values
                    category_val = values.get("category", "")
                    details_val = values.get("details", "")
                    evidence_val = values.get("evidence", "")
                    
                    # Process complaint using same logic as complaint_modal handler
                    # This is duplicated but necessary for persistence after bot restarts
                    guild = interaction.guild
                    if not guild:
                        return await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
                    
                    # Generate unique case_id with retry logic
                    created = now_utc()
                    max_retries = 10
                    case_id = None
                    
                    for attempt in range(max_retries):
                        timestamp_part = int(created.timestamp() * 1000000)
                        random_part = random.randint(1000, 9999)
                        user_part = interaction.user.id % 10000
                        case_id = f"OBS-{timestamp_part}-{user_part}-{random_part}"
                        
                        async with aiosqlite.connect(DB_PATH) as db:
                            cur = await db.execute(
                                "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                (guild.id, case_id)
                            )
                            exists = await cur.fetchone()
                        
                        if not exists:
                            break
                        
                        if attempt == max_retries - 1:
                            import time
                            case_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"
                    
                    created_iso = created.isoformat()

                    # Check for duplicates
                    async with aiosqlite.connect(DB_PATH) as db:
                        check_cur = await db.execute(
                            "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND created_at > datetime('now', '-5 seconds')",
                            (guild.id, interaction.user.id, category_val, details_val)
                        )
                        existing = await check_cur.fetchone()
                        if existing:
                            _processed_modal_submissions.discard(interaction_key)
                            await interaction.followup.send("This submission was already processed.", ephemeral=True)
                            return
                        
                        await db.execute(
                            "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (guild.id, case_id, interaction.user.id, created_iso, category_val, details_val, evidence_val, "OPEN", None, created_iso),
                        )
                        await db.commit()

                    complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
                    ch = guild.get_channel(complaints_id) if complaints_id else None
                    if not isinstance(ch, discord.TextChannel):
                        return await interaction.followup.send(
                            "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                            ephemeral=True,
                        )

                    # Type guard: ensure case_id is not None
                    if not case_id:
                        return await interaction.followup.send("Error: Failed to generate case ID.", ephemeral=True)

                    # Type narrowing: ch is now guaranteed to be discord.TextChannel
                    assert isinstance(ch, discord.TextChannel)

                    mod_role = get_mod_role(guild)
                    mention = mod_role.mention if mod_role else f"@{MOD_ROLE_NAME}"

                    desc = f"**Category:** {category_val}\n\n**Details:**\n{details_val}"
                    if evidence_val.strip():
                        desc += f"\n\n**Evidence:** {evidence_val}"

                    embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red(), client=bot)
                    embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

                    view = ComplaintModView(case_id)
                    msg = await ch.send(content=mention, embed=embed, view=view)  # type: ignore
                    bot.add_view(view)

                    # Create staff thread
                    thread_id: Optional[int] = None  # type: ignore
                    thread_name = format_thread_name(case_id, interaction.user, category_val, created_iso)
                    staff_thread: Optional[discord.Thread] = None  # type: ignore
                    try:
                        staff_thread = await ch.create_thread(  # type: ignore
                            name=thread_name,
                            type=discord.ChannelType.private_thread,
                            invitable=False,
                            reason="Private staff thread for complaint",
                        )
                        thread_id = staff_thread.id if staff_thread else None
                        if mod_role and staff_thread:
                            try:
                                await staff_thread.add_user(interaction.user)
                            except Exception:
                                pass
                    except Exception:
                        try:
                            staff_thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                            thread_id = staff_thread.id if staff_thread else None
                        except Exception:
                            staff_thread = None

                    if thread_id and staff_thread:
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                                (thread_id, guild.id, case_id),
                            )
                            await db.commit()
                        try:
                            await staff_thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps.", client=bot))
                        except Exception:
                            pass

                    await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "Docket Sealed",
                            f"Your docket entry has been sealed as **`{case_id}`**.\nYou'll receive DM docket updates as it progresses.",
                            color=discord.Color.green(),
                        ),
                        ephemeral=True,
                    )
                    logger.info(f"[modal] Successfully created complaint from auto-generated modal: {case_id}")
                    
                except Exception as e:
                    logger.error(f"[modal] Error processing auto-generated modal: {e}", exc_info=True)
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send("Error processing docket submission.", ephemeral=True)
                        else:
                            await interaction.response.send_message("Error processing docket submission.", ephemeral=True)
                    except Exception:
                        pass
                finally:
                    try:
                        await asyncio.sleep(2)
                        _processed_modal_submissions.discard(interaction_key)
                    except Exception:
                        pass
                return
        
        except Exception as e:
            logger.error(f"[modal] Error extracting data from unknown modal: {e}", exc_info=True)
        
        # If we can't handle it, defer and send a generic error message instead of letting discord.py handle it
        # (which would cause the "process_application_commands" error)
        logger.warning(f"[modal] Could not handle modal with custom_id: {cid} - sending generic error")
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("This modal is no longer valid. Please try again.", ephemeral=True)
            else:
                await interaction.followup.send("This modal is no longer valid. Please try again.", ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            # Interaction expired or already handled - can't send error message
            logger.warning(f"[modal] Could not send error message for unknown modal: {cid}")
        return
    
    # Only handle component interactions (buttons/selects) from here
    if interaction.type != discord.InteractionType.component:
        return

    try:
        cid = interaction.data.get("custom_id") if interaction.data else None
        if not cid:
            return

        # Complaints: open modal
        if cid == "complaints:open":
            # Check if interaction is still valid (not expired)
            if interaction.response.is_done():
                logger.warning(f"[button] complaints:open - interaction already done")
                return
            try:
                modal = ComplaintModal()
                await interaction.response.send_modal(modal)
                logger.info(f"[button] Sent ComplaintModal with custom_id: {modal.custom_id}")
                return
            except (discord.errors.NotFound, discord.errors.InteractionResponded) as e:
                logger.error(f"[button] complaints:open - interaction expired/already handled: {e}")
                return
            except Exception as e:
                logger.error(f"[button] complaints:open - error sending modal: {e}", exc_info=True)
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message("Failed to open docket form. Please try again.", ephemeral=True)
                except Exception:
                    pass
                return

        # Complaints: mod actions
        if cid.startswith("complaints:"):
            # complaints:{case_id}:{action}
            parts = cid.split(":")
            if len(parts) == 3:
                _, case_id, action = parts
                if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                    return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

                view = ComplaintModView(case_id)

                # Check if interaction has already been responded to
                if interaction.response.is_done():
                    logger.warning(f"[button] complaints action already handled: {case_id}:{action}")
                    return

                if action == "ack":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:ack - interaction expired/already handled: {e}")
                        return
                    await view.set_status(interaction, "ACKNOWLEDGED")
                    await interaction.followup.send(f"`{case_id}` marked reviewed.", ephemeral=True)
                    return

                if action == "resolve":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:resolve - interaction expired/already handled: {e}")
                        return
                    await view.set_status(interaction, "RESOLVED")
                    await interaction.followup.send(f"`{case_id}` closed.", ephemeral=True)
                    return

                if action == "reject":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:reject - interaction expired/already handled: {e}")
                        return
                    await view.set_status(interaction, "REJECTED")
                    await interaction.followup.send(f"`{case_id}` dismissed.", ephemeral=True)
                    return

                if action == "needinfo":
                    # Check if interaction is still valid
                    if interaction.response.is_done():
                        logger.warning(f"[button] Request Evidence - interaction already done: {case_id}")
                        return
                    try:
                        modal = RequestInfoModal(case_id)
                        await interaction.response.send_modal(modal)
                        logger.info(f"[button] Sent RequestInfoModal for case: {case_id}")
                        return
                    except (discord.errors.NotFound, discord.errors.InteractionResponded) as e:
                        logger.warning(f"[button] Request Evidence - interaction expired/already handled: {case_id}: {e}")
                        # Interaction expired - try to send error via followup if possible
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("The interaction expired. Please try clicking the button again.", ephemeral=True)
                        except Exception:
                            pass
                        return
                    except Exception as e:
                        logger.error(f"[button] Request Evidence - error sending modal: {case_id}: {e}", exc_info=True)
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("Failed to open evidence request form. Please try again.", ephemeral=True)
                            else:
                                await interaction.response.send_message("Failed to open evidence request form. Please try again.", ephemeral=True)
                        except Exception:
                            pass
                        return

        # Events: RSVP
        if cid.startswith("events:rsvp:"):
            rsvp_action = cid.split(":")[-1]
            view = RSVPView()
            if rsvp_action == "going":
                await view._set_rsvp(interaction, "GOING")
                return
            if rsvp_action == "maybe":
                await view._set_rsvp(interaction, "MAYBE")
                return
            if rsvp_action == "no":
                await view._set_rsvp(interaction, "NO")
                return

        # Voice: VC panel actions: vc:{vc_id}:{action}
        if cid.startswith("vc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                vc_id_s, action = parts[1], parts[2]
                try:
                    vc_id = int(vc_id_s)
                except ValueError:
                    return await interaction.response.send_message("Invalid channel reference.", ephemeral=True)

                # Permission check (owner or mods)
                member = interaction.user
                if not isinstance(member, discord.Member):
                    return await interaction.response.send_message("Not allowed.", ephemeral=True)

                allowed = is_mod(member)
                if not allowed:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (interaction.guild.id, vc_id),
                        )
                        row = await cur.fetchone()
                    allowed = bool(row and int(row[0]) == member.id)

                if not allowed:
                    return await interaction.response.send_message("Only the squad owner (or Obsidian Inheritor) may do that.", ephemeral=True)

                vc = interaction.guild.get_channel(vc_id)
                if not isinstance(vc, discord.VoiceChannel):
                    return await interaction.response.send_message("Channel not found.", ephemeral=True)

                # Helpers for @everyone overwrite tweaks
                async def edit_everyone(*, connect: Optional[bool] = None, view: Optional[bool] = None):
                    overwrites = vc.overwrites
                    base = overwrites.get(interaction.guild.default_role, discord.PermissionOverwrite())
                    if connect is not None:
                        base.connect = connect
                    if view is not None:
                        base.view_channel = view
                    overwrites[interaction.guild.default_role] = base

                    mod_role = get_mod_role(interaction.guild)
                    if mod_role:
                        m = overwrites.get(mod_role, discord.PermissionOverwrite())
                        m.view_channel = True
                        m.connect = True
                        overwrites[mod_role] = m

                    # Owner stays able to view/connect
                    owner_ow = overwrites.get(member, discord.PermissionOverwrite())
                    owner_ow.view_channel = True
                    owner_ow.connect = True
                    overwrites[member] = owner_ow

                    await vc.edit(overwrites=overwrites, reason="Obsidian VC panel action")

                if action == "rename":
                    await interaction.response.send_modal(RenameVCModal(vc_id))
                    return

                if action == "limit":
                    await interaction.response.send_message("Choose a squad limit:", view=SetLimitView(vc_id), ephemeral=True)
                    return

                if action == "lock":
                    await edit_everyone(connect=False)
                    await interaction.response.send_message("Sealed.", ephemeral=True)
                    return

                if action == "unlock":
                    await edit_everyone(connect=True)
                    await interaction.response.send_message("Unsealed.", ephemeral=True)
                    return

                if action == "hide":
                    await edit_everyone(view=False)
                    await interaction.response.send_message("Cloaked.", ephemeral=True)
                    return

                if action == "show":
                    await edit_everyone(view=True)
                    await interaction.response.send_message("Revealed.", ephemeral=True)
                    return

                if action == "invite":
                    await interaction.response.send_modal(InviteModal(vc_id))
                    return

                if action == "remove":
                    await interaction.response.send_modal(RemoveAccessModal(vc_id))
                    return

                if action == "transfer":
                    await interaction.response.send_modal(TransferOwnerModal(vc_id))
                    return

                if action == "disband":
                    await interaction.response.send_message("Cell dissolved.", ephemeral=True)
                    await delete_temp_vc_and_panel(interaction.guild, vc_id, reason="Disband via panel")
                    return

    except Exception as e:
        # Last-resort error handler - only for component/modal interactions
        # Do NOT handle errors for application commands - let discord.py handle them
        if interaction.type == discord.InteractionType.application_command:
            # Re-raise to let discord.py handle it
            raise
        
        # Also skip if this is a modal submission - it has its own error handler
        if interaction.type == discord.InteractionType.modal_submit:
            # Don't handle here - modal submission has its own handler
            # Filter out process_application_commands errors (they're not real errors)
            if "process_application_commands" in str(e):
                logger.warning(f"[outer_handler] Ignoring process_application_commands error in modal submission (likely stale/cached): {e}")
                return  # Don't send error message to user
            # But log other errors for debugging
            import traceback
            import sys
            error_msg = f"[outer_handler] Modal submission error (should be handled by modal handler): {e}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr, flush=True)
            print(error_msg, flush=True)
            return
        
        # For component interactions, handle the error
        import traceback
        import sys
        error_traceback = traceback.format_exc()
        error_msg = f"[outer_handler] Component interaction error: {e}\n{error_traceback}"
        logger.error(error_msg)
        print(error_msg, file=sys.stderr, flush=True)
        print(error_msg, flush=True)
        
        # Don't send error messages about process_application_commands - it's not a real error
        # This error message appears to be cached or from an old code path
        if "process_application_commands" in str(e):
            logger.warning(f"[outer_handler] Ignoring process_application_commands error (likely cached/stale): {e}")
            return  # Don't send error message to user
        
        # Don't send error messages for expired interactions (404) - we can't respond to them
        if isinstance(e, discord.errors.NotFound) and "Unknown interaction" in str(e):
            logger.warning(f"[outer_handler] Interaction expired (404), cannot send error message: {e}")
            return  # Interaction expired, can't respond
        
        # Only try to send error message if interaction is still valid
        try:
            if interaction.response.is_done():
                # Try followup, but it might also fail if interaction expired
                try:
                    await interaction.followup.send(f"Something went wrong: {str(e)}", ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    # Interaction expired or already handled - can't send error
                    logger.warning(f"[outer_handler] Could not send error via followup (interaction expired/handled)")
            else:
                try:
                    await interaction.response.send_message(f"Something went wrong: {str(e)}", ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    # Interaction already expired or handled
                    logger.warning(f"[outer_handler] Could not send error via response (interaction expired/handled)")
        except Exception as err:
            # If we can't send error message, log it
            logger.error(f"[outer_handler] Could not send error message: {err}", exc_info=True)


# --------------------- Join-to-create logic ---------------------


@tasks.loop(minutes=VC_CLEANUP_INTERVAL_MINUTES)
async def temp_vc_cleanup():
    cutoff = now_utc() - timedelta(minutes=VOICE_IDLE_DELETE_MINUTES)

    for guild in bot.guilds:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, last_nonempty_at FROM temp_vcs WHERE guild_id=?",
                (guild.id,),
            )
            rows = await cur.fetchall()

        for channel_id, last_nonempty_at in rows:
            vc = guild.get_channel(int(channel_id))
            if not isinstance(vc, discord.VoiceChannel):
                await delete_temp_vc_and_panel(guild, int(channel_id), reason="Cleanup missing VC")
                continue

            # Never delete join-to-create trigger
            create_id_s = await get_guild_setting(guild.id, "create_vc_channel_id")
            if create_id_s and create_id_s.isdigit() and vc.id == int(create_id_s):
                continue

            try:
                last_dt = datetime.fromisoformat(last_nonempty_at)
            except Exception:
                last_dt = now_utc()

            if len(vc.members) == 0 and last_dt < cutoff:
                await delete_temp_vc_and_panel(guild, vc.id, reason="Temp VC idle cleanup")


@temp_vc_cleanup.before_loop
async def before_temp_vc_cleanup():
    await bot.wait_until_ready()


@tasks.loop(minutes=EVENT_REMINDER_LOOP_MINUTES)
async def event_reminder_loop():
    for guild in bot.guilds:
        events_id = await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
        ch = guild.get_channel(events_id) if events_id else None
        if not isinstance(ch, discord.TextChannel):
            continue
        # Type narrowing: ch is now guaranteed to be discord.TextChannel
        assert isinstance(ch, discord.TextChannel)

        now_ts = int(now_utc().timestamp())
        soon_ts = int((now_utc() + timedelta(minutes=EVENT_REMINDER_MINUTES_BEFORE)).timestamp())

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT message_id,title,start_ts,role_id FROM events "
                "WHERE guild_id=? AND reminder_sent=0 AND start_ts BETWEEN ? AND ?",
                (guild.id, now_ts, soon_ts),
            )
            rows = await cur.fetchall()

        for message_id, title, start_ts, role_id in rows:
            mention = ""
            if int(role_id or 0):
                role = guild.get_role(int(role_id))
                if role:
                    mention = role.mention

            if ch:
                await ch.send(
                    content=mention if mention else None,
                    embed=obsidian_embed(
                        "⏳ Operation Reminder",
                        f"**{title}** begins in ~{EVENT_REMINDER_MINUTES_BEFORE} minutes.\n"
                        f"**Time:** <t:{int(start_ts)}:F>  _( <t:{int(start_ts)}:R> )_",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                )

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE events SET reminder_sent=1 WHERE guild_id=? AND message_id=?",
                    (guild.id, int(message_id)),
                )
                await db.commit()


@event_reminder_loop.before_loop
async def before_event_reminder_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=VOICE_REWARD_INTERVAL_MINUTES)
async def voice_reward_loop():
    """Award coins to users based on voice channel activity."""
    if not ECONOMY_ENABLED:
        return
    
    now = now_utc()
    
    for guild in bot.guilds:
        async with aiosqlite.connect(DB_PATH) as db:
            # Get all active voice sessions
            cur = await db.execute("""
                SELECT user_id, channel_id, joined_at, last_reward_at, total_minutes
                FROM voice_activity
                WHERE guild_id=?
            """, (guild.id,))
            rows = await cur.fetchall()
            
            for user_id, channel_id, joined_at_str, last_reward_at_str, total_minutes in rows:
                try:
                    user = guild.get_member(user_id)
                    if not user:
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.VoiceChannel):
                        continue
                    
                    # Check if user is still in the channel and not muted/deafened
                    if user.voice and user.voice.channel and user.voice.channel.id == channel_id:
                        if user.voice.self_mute or user.voice.self_deaf:
                            continue
                    else:
                        # User left, remove tracking
                        await db.execute(
                            "DELETE FROM voice_activity WHERE guild_id=? AND user_id=? AND channel_id=?",
                            (guild.id, user_id, channel_id),
                        )
                        await db.commit()
                        continue
                    
                    # Calculate minutes since last reward (or since join)
                    joined_at = datetime.fromisoformat(joined_at_str)
                    if last_reward_at_str:
                        last_reward_at = datetime.fromisoformat(last_reward_at_str)
                        minutes_since = (now - last_reward_at).total_seconds() / 60
                    else:
                        minutes_since = (now - joined_at).total_seconds() / 60
                    
                    # Award coins for full minutes
                    if minutes_since >= MIN_VOICE_MINUTES_FOR_REWARD:
                        minutes_to_reward = int(minutes_since)
                        coins = minutes_to_reward * COINS_PER_MINUTE_VOICE
                        
                        if coins > 0:
                            await add_coins(
                                guild.id,
                                user_id,
                                coins,
                                "VOICE",
                                f"Voice activity in #{channel.name}",
                            )
                            
                            # Award XP (if enabled)
                            from utils import XP_ENABLED, XP_PER_MINUTE_VOICE
                            if XP_ENABLED:
                                xp_amount = minutes_to_reward * XP_PER_MINUTE_VOICE
                                if xp_amount > 0:
                                    leveled_up = await add_xp(
                                        guild.id,
                                        user_id,
                                        xp_amount,
                                        "VOICE",
                                    )
                                    if leveled_up:
                                        xp, level, total_xp = await get_user_xp(guild.id, user_id)
                                        logger.info(f"User {user_id} leveled up to level {level} in guild {guild.id} (voice activity)")
                            
                            # Update tracking
                            new_total = total_minutes + minutes_to_reward
                            await db.execute("""
                                UPDATE voice_activity
                                SET last_reward_at=?, total_minutes=?
                                WHERE guild_id=? AND user_id=? AND channel_id=?
                            """, (now.isoformat(), new_total, guild.id, user_id, channel_id))
                            await db.commit()
                
                except Exception as e:
                    print(f"[economy] Error processing voice reward for {user_id} in {guild.id}: {e}")
                    continue


@voice_reward_loop.before_loop
async def before_voice_reward_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=1)  # Check every hour for Baro
async def baro_check_loop():
    """Check for Baro Ki'Teer arrivals and send notifications."""
    try:
        await check_and_notify_baro_arrival()
    except Exception as e:
        logger.error(f"Error in baro_check_loop: {e}", exc_info=True)


@baro_check_loop.before_loop
async def before_baro_check_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=1)  # Check every hour for expired LFG posts
async def lfg_expire_loop():
    """Auto-expire LFG posts that have passed their expiry time."""
    try:
        from datetime import datetime, timezone
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now(timezone.utc).isoformat()
            
            # Find expired posts
            cur = await db.execute("""
                SELECT id, guild_id, channel_id, message_id
                FROM lfg_posts
                WHERE status='OPEN' AND expires_at < ?
            """, (now,))
            
            expired = await cur.fetchall()
            
            for lfg_id, guild_id, channel_id, message_id in expired:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    
                    try:
                        message = await channel.fetch_message(message_id)
                        
                        # Update embed
                        embed = message.embeds[0] if message.embeds else None
                        if embed:
                            embed.color = discord.Color.grey()
                            embed.set_footer(text="⏰ Expired")
                            
                            # Disable buttons
                            view = discord.ui.View()
                            for item in message.components[0].children if message.components else []:
                                if hasattr(item, 'disabled'):
                                    item.disabled = True
                                    view.add_item(item)
                            
                            await message.edit(embed=embed, view=view)
                    except discord.NotFound:
                        pass
                    
                    # Mark as expired in database
                    await db.execute(
                        "UPDATE lfg_posts SET status='EXPIRED' WHERE id=?",
                        (lfg_id,)
                    )
                    await db.commit()
                except Exception as e:
                    logger.error(f"Error expiring LFG post {lfg_id}: {e}", exc_info=True)
                    continue
    except Exception as e:
        logger.error(f"Error in lfg_expire_loop: {e}", exc_info=True)


@lfg_expire_loop.before_loop
async def before_lfg_expire_loop():
    await bot.wait_until_ready()


# --------------------- Economy Commands ---------------------
# Economy commands are now loaded from commands/economy/ folder via load_all_commands()


# --------------------- Install / startup hooks ---------------------
@bot.event
async def on_guild_join(guild: discord.Guild):
    # Fired when the bot is installed into a server
    try:
        await ensure_core_channels(guild)
        await ensure_join_to_create_channel(guild)
        print(f"[install] Ensured join-to-create in {guild.name}")
    except Exception as e:
        print(f"[install] Setup failed in {guild.name}: {e}")


@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} ({bot.user.id})")

    # Ensure channels + join-to-create exist on startup (covers restarts)
    for g in bot.guilds:
        try:
            await ensure_core_channels(g)
            await ensure_join_to_create_channel(g)
        except Exception as e:
            print(f"[startup] Ensure failed in {g.name}: {e}")

    # Re-register persistent views
    bot.add_view(ComplaintPanel())
    bot.add_view(RSVPView())

    # Re-register VC panel views for existing temp VCs (so their buttons keep working after restart)
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT channel_id FROM temp_vcs WHERE guild_id=?",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (channel_id,) in rows:
                try:
                    bot.add_view(VCPanelView(int(channel_id)))
                except Exception:
                    pass

    # Re-register LFG views for active posts
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT id FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (lfg_id,) in rows:
                try:
                    from commands.warframe.lfg import LFGView
                    bot.add_view(LFGView(int(lfg_id)))
                except Exception:
                    pass

    # Re-register complaint views for open-ish cases
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT case_id FROM complaints WHERE guild_id=? AND status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (case_id,) in rows:
                try:
                    bot.add_view(ComplaintModView(str(case_id)))
                except Exception:
                    pass

    if not temp_vc_cleanup.is_running():
        temp_vc_cleanup.start()
    if not event_reminder_loop.is_running():
        event_reminder_loop.start()
    if ECONOMY_ENABLED and not voice_reward_loop.is_running():
        voice_reward_loop.start()
    if not baro_check_loop.is_running():
        baro_check_loop.start()
    if not lfg_expire_loop.is_running():
        lfg_expire_loop.start()
    if not cycle_check_loop.is_running():
        cycle_check_loop.start()


async def main():
    await init_db()
    try:
        await bot.start(TOKEN)
    except discord.errors.PrivilegedIntentsRequired as e:
        print("\n" + "="*60)
        print("ERROR: Privileged Intents Required")
        print("="*60)
        print("\nThe bot requires privileged intents that must be enabled")
        print("in the Discord Developer Portal.\n")
        print("Required intents:")
        print("  - Server Members Intent (PRIVILEGED)")
        print("\nTo enable:")
        print("1. Go to: https://discord.com/developers/applications/")
        print("2. Select your application")
        print("3. Go to the 'Bot' section")
        print("4. Enable 'SERVER MEMBERS INTENT' under Privileged Gateway Intents")
        print("5. Save changes and restart the bot\n")
        print("="*60 + "\n")
        raise
    except KeyboardInterrupt:
        print("\n[shutdown] Bot stopped by user")
    except Exception as e:
        print(f"\n[error] Bot crashed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
