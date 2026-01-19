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

# Database path - use consistent location
# On Railway, use /tmp for ephemeral storage or mount a persistent volume
# For persistent storage on Railway, set DB_PATH env var to a mounted volume path
# Example: DB_PATH=/data/obsidian_clanbot.db (if you mount a volume at /data)
DB_PATH = os.getenv("DB_PATH", "obsidian_clanbot.db")

# Bot version - starts at 1.2.0, auto-increments on changes
BOT_VERSION = os.getenv("BOT_VERSION", "1.2.0")
BOT_CHANGELOG = os.getenv("BOT_CHANGELOG", "")  # Optional: changelog text for this version

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
INTENTS.message_content = True  # Required for reading message content (economy/XP system)
INTENTS.guilds = True
INTENTS.members = True
INTENTS.voice_states = True



# Import utilities and modules
from utils import obsidian_embed, extract_id, get_mod_role, is_mod, parse_time_natural, display_case_status
from database import (
    get_user_balance, add_coins, remove_coins, transfer_coins,
    get_user_xp, add_xp, calculate_level, xp_for_level, xp_for_next_level,
    get_guild_setting, set_guild_setting, now_utc, DB_PATH
)
from warframe_api import fetch_baro_data, fetch_cycle_data, get_all_cycles, get_baro_status
from channels import (
    resolve_channel_id, find_or_create_text_channel,
    resolve_temp_vc_category, ensure_join_to_create_channel, ensure_core_channels,
    delete_temp_vc_and_panel, delete_vc_panel_message
)
from modals import RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal, ComplaintModal, RequestInfoModal
from views import VCPanelView, ComplaintPanel, ComplaintModView, RSVPView, SetLimitView, SetLimitSelect
from tasks import setup_tasks




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
        "commands.general.member_count",
        "commands.general.setup_obsidian",
        "commands.general.setup_docket",
        "commands.general.sync_commands",
        "commands.general.welcome_setup",
        "commands.general.milestones",
        "commands.general.achievements",
        "commands.general.webhooks",
        # Music commands
        "commands.music.music",
        # Event commands
        "commands.events.event_create",
        # Complaint commands
        "commands.complaints.submit_complaint",
        "commands.complaints.request_help",
        # Ticket commands
        "commands.tickets.ticket",
        # Suggestion commands
        "commands.suggestions.suggest",
        "commands.suggestions.manage_suggestions",
        # Application commands
        "commands.applications.application",
        "commands.applications.application_setup",
        "commands.applications.manage_applications",
        # Update log commands
        "commands.updates.update_log",
        "commands.updates.update_log_setup",
        "commands.updates.force_version_update",
        # Trading commands
        "commands.trading.trade",
        "commands.trading.trade_price",
        "commands.trading.trade_search",
        "commands.trading.trade_list",
        "commands.trading.trade_setup",
        # Moderation commands
        "commands.moderation.purge",
        "commands.moderation.reaction_roles",
        "commands.moderation.automod_setup",
        "commands.moderation.automod_status",
        "commands.moderation.roles",
        "commands.moderation.level_roles",
        "commands.moderation.logging",
        "commands.moderation.snipe",
        "commands.moderation.warn",
        "commands.moderation.starboard",
        "commands.moderation.role_menu",
        # Economy commands
        "commands.economy.balance",
        "commands.economy.leaderboard",
        "commands.economy.transfer",
        "commands.economy.daily",
        "commands.economy.xp",
        "commands.economy.xpleaderboard",
        "commands.economy.add_coins",
        "commands.economy.manage_xp",
        "commands.economy.invest",
        "commands.economy.shop",
        "commands.economy.shop_manage",
        "commands.economy.gambling",
        "commands.economy.pets",
        # Warframe commands
        "commands.warframe.baro",
        "commands.warframe.baro_notify",
        "commands.warframe.lfg",
        "commands.warframe.lfg_list",
        "commands.warframe.cycles",
        "commands.warframe.cycle_notify",
        "commands.warframe.invasions",
        "commands.warframe.invasion_notify",
        "commands.warframe.archon",
        "commands.warframe.archon_notify",
        "commands.warframe.warframe_event_notify",
        "commands.warframe.resource",
        "commands.warframe.duviri",
        "commands.warframe.alerts",
        "commands.warframe.alerts_notify",
        "commands.warframe.devstream_notify",
        "commands.warframe.dojo",
        # Activity commands
        "commands.activity.activity",
        "commands.activity.activity_leaderboard",
        # General commands
        "commands.general.afk",
        "commands.general.server_stats",
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
        CREATE TABLE IF NOT EXISTS baro_live_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            expiry_time TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, channel_id, message_id)
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
            status TEXT NOT NULL DEFAULT 'OPEN',
            thread_id INTEGER
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

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notification_settings (
            guild_id INTEGER NOT NULL,
            reward_lower TEXT NOT NULL,
            reward_display TEXT NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS invasion_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            invasion_id TEXT NOT NULL,
            reward_lower TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, invasion_id, reward_lower)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notification_settings (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS archon_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            archon_boss TEXT NOT NULL,
            expiry_time TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, archon_boss, expiry_time)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_count_channels (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            channel_type TEXT NOT NULL DEFAULT 'voice',
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_event_settings (
            guild_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warframe_discord_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            warframe_event_id TEXT NOT NULL,
            discord_event_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, warframe_event_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            suggestion_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            question_order INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            UNIQUE(guild_id, question_order)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
            current_question_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            submitted_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            review_note TEXT,
            message_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS application_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            response_text TEXT NOT NULL,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES application_questions(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS update_log_posted_versions (
            guild_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, version)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_version_tracking (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_version TEXT NOT NULL,
            feature_hash TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            previous_commands TEXT
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reaction_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id, emoji)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS welcome_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS leave_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            message TEXT,
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT NOT NULL,
            winner_count INTEGER NOT NULL DEFAULT 1,
            end_time TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            ended INTEGER NOT NULL DEFAULT 0,
            ended_at TEXT,
            required_role_id INTEGER,
            min_level INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            entered_at TEXT NOT NULL,
            UNIQUE(giveaway_id, user_id),
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            spam_enabled INTEGER NOT NULL DEFAULT 1,
            spam_threshold INTEGER NOT NULL DEFAULT 5,
            spam_interval INTEGER NOT NULL DEFAULT 10,
            caps_enabled INTEGER NOT NULL DEFAULT 1,
            caps_threshold INTEGER NOT NULL DEFAULT 70,
            caps_min_length INTEGER NOT NULL DEFAULT 10,
            links_enabled INTEGER NOT NULL DEFAULT 0,
            links_whitelist TEXT,
            mention_enabled INTEGER NOT NULL DEFAULT 1,
            mention_limit INTEGER NOT NULL DEFAULT 5,
            punishment_action TEXT NOT NULL DEFAULT 'delete',
            punishment_duration INTEGER,
            log_channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            message_content TEXT,
            action_taken TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS auto_mod_spam_tracking (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 1,
            first_message_time TEXT NOT NULL,
            last_message_time TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")


        await db.execute("""
        CREATE TABLE IF NOT EXISTS self_assignable_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            category TEXT,
            description TEXT,
            max_roles INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, role_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS level_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, level)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS afk_users (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            set_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_stats_channels (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            stats_type TEXT NOT NULL DEFAULT 'members',
            enabled INTEGER NOT NULL DEFAULT 1
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS alert_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            alert_id TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, alert_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS devstream_notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            devstream_date TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            UNIQUE(guild_id, devstream_date, notification_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            interest_rate REAL NOT NULL DEFAULT 0.05,
            invested_at TEXT NOT NULL,
            maturity_date TEXT NOT NULL,
            collected INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, invested_at)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS log_channels (
            guild_id INTEGER NOT NULL,
            log_type TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, log_type)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS deleted_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT,
            author_name TEXT,
            author_avatar TEXT,
            attachments TEXT,
            embeds TEXT,
            deleted_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS edited_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            old_content TEXT,
            new_content TEXT,
            author_name TEXT,
            edited_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS member_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            milestone_type TEXT NOT NULL,
            milestone_value INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0,
            UNIQUE(guild_id, user_id, milestone_type, milestone_value)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            UNIQUE(guild_id, user_id, achievement_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS achievement_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            requirement TEXT,
            reward_coins INTEGER DEFAULT 0,
            reward_xp INTEGER DEFAULT 0,
            UNIQUE(achievement_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS music_queues (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            voice_channel_id INTEGER NOT NULL,
            current_track TEXT,
            queue_json TEXT,
            is_playing INTEGER NOT NULL DEFAULT 0,
            volume INTEGER NOT NULL DEFAULT 50,
            updated_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            endpoint_name TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            event_types TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, endpoint_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            price INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_value TEXT,
            stock INTEGER DEFAULT -1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, item_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            price_paid INTEGER NOT NULL,
            purchased_at TEXT NOT NULL,
            FOREIGN KEY (item_id) REFERENCES shop_items(id)
        )""")
        
        # Add previous_commands column if it doesn't exist (for existing databases)
        # Check if column exists first to avoid errors
        try:
            cur = await db.execute("PRAGMA table_info(bot_version_tracking)")
            columns = await cur.fetchall()
            column_names = [col[1] for col in columns]
            if "previous_commands" not in column_names:
                await db.execute("ALTER TABLE bot_version_tracking ADD COLUMN previous_commands TEXT")
                await db.commit()
                logger.info("[db] Added previous_commands column to bot_version_tracking table")
        except Exception as e:
            logger.warning(f"[db] Error checking/adding previous_commands column: {e}")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            listing_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            price INTEGER,
            quantity INTEGER DEFAULT 1,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            platform TEXT NOT NULL DEFAULT 'pc'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS trading_channel_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            commands_used INTEGER NOT NULL DEFAULT 0,
            events_attended INTEGER NOT NULL DEFAULT 0,
            voice_minutes INTEGER NOT NULL DEFAULT 0,
            messages_sent INTEGER NOT NULL DEFAULT 0,
            last_activity_date TEXT NOT NULL,
            weekly_score INTEGER NOT NULL DEFAULT 0,
            monthly_score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            activity_date TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )""")

        # Ticket system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            ticket_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT,
            closed_by INTEGER,
            UNIQUE(guild_id, ticket_id)
        )""")

        # Gambling tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS gambling_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            game_type TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            win_amount INTEGER NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        # Server rules tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS server_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            rule_number INTEGER NOT NULL,
            rule_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, rule_number)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            accepted_at TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Poll system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            ends_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            poll_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            option_index INTEGER NOT NULL,
            voted_at TEXT NOT NULL,
            PRIMARY KEY (poll_id, user_id),
            FOREIGN KEY (poll_id) REFERENCES polls(id)
        )""")

        # Warn system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS warn_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            max_warnings INTEGER NOT NULL DEFAULT 3,
            action_after_max TEXT NOT NULL DEFAULT 'mute',
            mute_duration INTEGER,
            log_channel_id INTEGER
        )""")

        # Reminder system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER,
            reminder_text TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        )""")

        # Starboard tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            threshold INTEGER NOT NULL DEFAULT 5,
            emoji TEXT NOT NULL DEFAULT '⭐'
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS starboard_messages (
            guild_id INTEGER NOT NULL,
            original_message_id INTEGER NOT NULL,
            starboard_message_id INTEGER NOT NULL,
            stars INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, original_message_id)
        )""")

        # Reputation system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reputation_points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reputation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            giver_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )""")

        # Twitch integration tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_settings (
            guild_id INTEGER NOT NULL PRIMARY KEY,
            channel_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 0
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS twitch_streamers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            streamer_name TEXT NOT NULL,
            twitch_user_id TEXT,
            last_live_status INTEGER NOT NULL DEFAULT 0,
            last_notified_at TEXT,
            UNIQUE(guild_id, streamer_name)
        )""")

        # Role menu tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            max_roles INTEGER,
            UNIQUE(guild_id, message_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS role_menu_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            emoji TEXT,
            description TEXT,
            FOREIGN KEY (menu_id) REFERENCES role_menus(id) ON DELETE CASCADE
        )""")

        # Clan Dojo tracker tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            research_name TEXT NOT NULL,
            research_type TEXT NOT NULL,
            required_resources TEXT,
            current_resources TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT,
            completed_at TEXT,
            UNIQUE(guild_id, research_name)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS dojo_decorations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            decoration_name TEXT NOT NULL,
            room_location TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL
        )""")

        # Pet system tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            pet_name TEXT NOT NULL,
            pet_type TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            experience INTEGER NOT NULL DEFAULT 0,
            hunger INTEGER NOT NULL DEFAULT 100,
            happiness INTEGER NOT NULL DEFAULT 100,
            last_fed_at TEXT,
            last_played_at TEXT,
            created_at TEXT NOT NULL
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS pet_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_type TEXT NOT NULL UNIQUE,
            base_price INTEGER NOT NULL,
            max_level INTEGER NOT NULL DEFAULT 100,
            description TEXT
        )""")

        await db.commit()


# Economy, XP, and guild setting functions are now in database.py


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


# Warframe API functions are now in warframe_api.py
# check_and_notify_baro_arrival is now in tasks.py


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


# Channel resolution functions are now in channels.py


# Voice panel modals and views are now in modals.py and views.py


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    """Post a VC control panel message."""
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


# Complaint and Event modals/views are now in modals.py and views.py


# --------------------- Slash Commands ---------------------
# Commands are now loaded from commands/ folder via load_all_commands()


# --------------------- Auto-Moderation Event Handlers ---------------------
async def check_auto_mod(message: discord.Message) -> bool:
    """Check message for auto-moderation violations. Returns True if message should be deleted/punished."""
    from database import (
        get_auto_mod_settings, get_spam_tracking, update_spam_tracking,
        reset_spam_tracking, log_auto_mod_violation
    )
    from utils import is_mod
    
    if not message.guild or message.author.bot:
        return False
    
    # Ignore moderators
    if isinstance(message.author, discord.Member) and is_mod(message.author):
        return False
    
    settings = await get_auto_mod_settings(message.guild.id)
    if not settings or not settings["enabled"]:
        return False
    
    violation_type = None
    action_taken = "none"
    
    # Check for spam
    if settings["spam_enabled"]:
        now_iso = now_utc().isoformat()
        tracking = await get_spam_tracking(message.guild.id, message.author.id)
        
        if tracking:
            # Parse timestamps
            first_msg_time = datetime.fromisoformat(tracking["first_message_time"])
            last_msg_time = datetime.fromisoformat(tracking["last_message_time"])
            time_diff = (now_utc() - first_msg_time).total_seconds()
            
            # Check if we're still within the interval window
            if time_diff <= settings["spam_interval"]:
                # Increment count
                new_count = tracking["message_count"] + 1
                await update_spam_tracking(
                    message.guild.id,
                    message.author.id,
                    new_count,
                    tracking["first_message_time"],
                    now_iso
                )
                
                # Check if threshold exceeded
                if new_count >= settings["spam_threshold"]:
                    violation_type = "spam"
                    await reset_spam_tracking(message.guild.id, message.author.id)
            else:
                # Window expired, reset
                await update_spam_tracking(
                    message.guild.id,
                    message.author.id,
                    1,
                    now_iso,
                    now_iso
                )
        else:
            # First message
            await update_spam_tracking(
                message.guild.id,
                message.author.id,
                1,
                now_iso,
                now_iso
            )
    
    # Check for caps lock
    if not violation_type and settings["caps_enabled"] and len(message.content) >= settings["caps_min_length"]:
        caps_count = sum(1 for c in message.content if c.isupper())
        caps_percent = (caps_count / len(message.content)) * 100 if message.content else 0
        
        if caps_percent >= settings["caps_threshold"]:
            violation_type = "caps"
    
    # Check for links
    if not violation_type and settings["links_enabled"]:
        # Check for URLs (basic regex)
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        if re.search(url_pattern, message.content):
            # Check whitelist if exists
            whitelist = settings["links_whitelist"].split(",") if settings["links_whitelist"] else []
            if whitelist:
                # Check if any whitelisted domain is in the message
                allowed = any(domain.strip() in message.content.lower() for domain in whitelist if domain.strip())
                if not allowed:
                    violation_type = "links"
            else:
                # No whitelist, all links blocked
                violation_type = "links"
    
    # Check for mention spam
    if not violation_type and settings["mention_enabled"]:
        mention_count = len(message.mentions) + len(message.role_mentions) + len(message.channel_mentions)
        if mention_count > settings["mention_limit"]:
            violation_type = "mention"
    
    # If violation detected, apply punishment
    if violation_type:
        action = settings["punishment_action"]
        duration = settings["punishment_duration"]
        
        try:
            # Delete message
            await message.delete()
            action_taken = "delete"
            
            # Apply additional punishment
            if action == "warn":
                action_taken = "delete + warn"
                # Could send a DM warning here
                
            elif action == "timeout" and isinstance(message.author, discord.Member):
                if duration:
                    timeout_until = now_utc() + timedelta(minutes=duration)
                    await message.author.timeout(timeout_until, reason=f"Auto-mod: {violation_type}")
                    action_taken = f"delete + timeout ({duration}m)"
                else:
                    action_taken = "delete + timeout (no duration set)"
                    
            elif action == "kick" and isinstance(message.author, discord.Member):
                try:
                    await message.author.kick(reason=f"Auto-mod: {violation_type}")
                    action_taken = "delete + kick"
                except discord.Forbidden:
                    action_taken = "delete (kick failed - no permission)"
            
            # Log violation
            await log_auto_mod_violation(
                message.guild.id,
                message.author.id,
                violation_type,
                message.content[:500],
                action_taken
            )
            
            # Send log message if channel is set
            if settings["log_channel_id"]:
                log_channel = message.guild.get_channel(settings["log_channel_id"])
                if isinstance(log_channel, discord.TextChannel):
                    embed = obsidian_embed(
                        f"🛡️ Auto-Moderation Action: {violation_type.upper()}",
                        f"**User:** {message.author.mention} ({message.author.id})\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Action:** {action_taken}\n"
                        f"**Message:** {message.content[:200]}",
                        color=discord.Color.red(),
                        client=bot,
                    )
                    try:
                        await log_channel.send(embed=embed)
                    except Exception:
                        pass  # Log channel might be deleted or no permission
            
            return True  # Message was handled
            
        except discord.NotFound:
            # Message already deleted
            return True
        except discord.Forbidden:
            # No permission to delete/punish
            logger.warning(f"[automod] No permission to punish {message.author.id} in {message.guild.id}")
            return False
        except Exception as e:
            logger.error(f"[automod] Error handling violation: {e}", exc_info=True)
            return False
    
    return False  # No violation or message not deleted


# --------------------- Economy Event Handlers ---------------------
@bot.event
async def on_message(message: discord.Message):
    """Check for auto-moderation violations and award coins for text messages."""
    # Ignore bot messages and DMs
    if message.author.bot or not message.guild:
        return
    
    # Check auto-moderation first (this may delete the message)
    violation_handled = await check_auto_mod(message)
    if violation_handled:
        return  # Message was deleted/punished, don't process economy
    
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
            # User leveled up! Assign level roles
            xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
            logger.info(f"User {message.author.id} leveled up to level {level} in guild {message.guild.id}")
            
            # Assign level roles
            from database import get_all_level_roles_up_to
            level_roles = await get_all_level_roles_up_to(message.guild.id, level)
            if level_roles:
                roles_to_add = []
                for lr in level_roles:
                    role = message.guild.get_role(lr["role_id"])
                    if role and role not in message.author.roles:
                        roles_to_add.append(role)
                
                if roles_to_add:
                    try:
                        await message.author.add_roles(*roles_to_add, reason=f"Leveled up to level {level}")
                        logger.info(f"Assigned level roles to {message.author.id}: {[r.id for r in roles_to_add]}")
                    except Exception as e:
                        logger.error(f"Error assigning level roles: {e}")
        
        # Check for level milestones and achievements
        xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
        from database import check_and_record_milestone, check_and_unlock_achievement, initialize_achievement_definitions
        
        # Initialize achievements if needed
        await initialize_achievement_definitions()
        
        # Check level milestones
        level_milestones = [10, 25, 50, 100]
        for milestone_level in level_milestones:
            if level >= milestone_level:
                milestone_achieved = await check_and_record_milestone(
                    message.guild.id, message.author.id, "level", milestone_level
                )
                if milestone_achieved:
                    # Unlock corresponding achievement
                    achievement_id = f"level_{milestone_level}"
                    await check_and_unlock_achievement(message.guild.id, message.author.id, achievement_id, bot)
        
        # Check message count milestones (get from activity_stats)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT messages_sent FROM activity_stats
                WHERE guild_id=? AND user_id=?
            """, (message.guild.id, message.author.id))
            row = await cur.fetchone()
            message_count = row[0] if row else 0
        
        # Update message count
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO activity_stats (guild_id, user_id, messages_sent, last_activity_date)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    messages_sent = messages_sent + 1,
                    last_activity_date = excluded.last_activity_date
            """, (message.guild.id, message.author.id, now_utc().isoformat()))
            await db.commit()
        
        # Check message count milestones
        message_milestones = [1, 100, 1000, 10000]
        for milestone_count in message_milestones:
            if message_count + 1 >= milestone_count:
                milestone_achieved = await check_and_record_milestone(
                    message.guild.id, message.author.id, "message_count", milestone_count
                )
                if milestone_achieved:
                    # Unlock corresponding achievement
                    achievement_map = {
                        1: "first_message",
                        100: "hundred_messages",
                        1000: "thousand_messages",
                        10000: "ten_thousand_messages"
                    }
                    if milestone_count in achievement_map:
                        await check_and_unlock_achievement(
                            message.guild.id, message.author.id, achievement_map[milestone_count], bot
                        )
    
    # Handle AFK system
    from database import get_afk_status, remove_afk
    # Check if message author is mentioned and they're AFK
    if message.mentions:
        for mentioned_user in message.mentions:
            if mentioned_user.id != message.author.id and not mentioned_user.bot:
                afk_status = await get_afk_status(message.guild.id, mentioned_user.id)
                if afk_status:
                    reason_text = f" - {afk_status['reason']}" if afk_status['reason'] else ""
                    try:
                        await message.channel.send(
                            embed=obsidian_embed(
                                "💤 User is AFK",
                                f"{mentioned_user.mention} is currently AFK{reason_text}",
                                color=discord.Color.orange(),
                                client=bot,
                            )
                        )
                    except:
                        pass  # Can't send message, that's okay
    
    # Check if message author is AFK and remove it
    if not message.author.bot:
        afk_status = await get_afk_status(message.guild.id, message.author.id)
        if afk_status:
            await remove_afk(message.guild.id, message.author.id)
            # Remove [AFK] from nickname
            if isinstance(message.author, discord.Member):
                try:
                    if message.author.display_name.startswith("[AFK]"):
                        new_nick = message.author.display_name.replace("[AFK] ", "").replace("[AFK]", "").strip()
                        if not new_nick:
                            new_nick = None
                        await message.author.edit(nick=new_nick)
                except:
                    pass  # Can't edit nickname, that's okay


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
                    # First, get existing total_minutes if any
                    cur = await db.execute("""
                        SELECT total_minutes FROM voice_activity
                        WHERE guild_id=? AND user_id=? AND channel_id=?
                    """, (member.guild.id, member.id, after.channel.id))
                    row = await cur.fetchone()
                    existing_minutes = row[0] if row else 0
                    
                    # Now insert or replace with preserved total_minutes
                    await db.execute("""
                        INSERT OR REPLACE INTO voice_activity (guild_id, user_id, channel_id, joined_at, last_reward_at, total_minutes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (member.guild.id, member.id, after.channel.id, now.isoformat(), None, existing_minutes))
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
        # Track command usage for activity (skip activity commands themselves to avoid recursion)
        if isinstance(interaction.user, discord.Member) and interaction.guild:
            command_name = interaction.data.get("name", "") if interaction.data else ""
            if command_name not in ["activity", "activity_leaderboard"]:  # Don't track these
                try:
                    from database import track_command_usage
                    await track_command_usage(interaction.guild.id, interaction.user.id)
                except Exception as e:
                    logger.debug(f"Failed to track command usage: {e}")
        # Do nothing else - let discord.py's built-in handler process it
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
                    await interaction.followup.send("Sorry, but you are not an Administrator in this server.", ephemeral=True)
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
                view = ComplaintModView(case_id)
                await view.set_status(interaction, "NEEDS INFO", bot=bot, dm_override=False)

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
                
                # Check for duplicate BEFORE marking as processed (fixes race condition)
                async with aiosqlite.connect(DB_PATH) as db:
                    # Check if this exact submission already exists (same user, same content, within last 5 seconds)
                    # Convert ISO 8601 datetime to SQLite datetime format for proper comparison
                    # Use datetime(created_at) to convert ISO format to SQLite datetime, then compare
                    check_cur = await db.execute(
                        "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND datetime(created_at) > datetime('now', '-5 seconds')",
                        (guild.id, interaction.user.id, category_val, details_val)
                    )
                    existing = await check_cur.fetchone()
                    if existing:
                        # Duplicate detected - don't process
                        logger.info(f"[modal] Duplicate submission detected: {interaction_key}")
                        await interaction.followup.send("This submission was already processed.", ephemeral=True)
                        return
                
                # Mark as processing AFTER duplicate check passes
                _processed_modal_submissions.add(interaction_key)
                logger.info(f"[modal] Processing complaint submission: {interaction_key}")
                
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
                    
                    # If we've exhausted retries, use a more unique approach and verify it
                    if attempt == max_retries - 1:
                        # Fallback: use full timestamp with nanoseconds simulation
                        import time
                        fallback_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"
                        
                        # Verify fallback ID is unique before using it
                        async with aiosqlite.connect(DB_PATH) as db:
                            cur = await db.execute(
                                "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                (guild.id, fallback_id)
                            )
                            fallback_exists = await cur.fetchone()
                        
                        if not fallback_exists:
                            case_id = fallback_id
                        else:
                            # Last resort: use timestamp + user_id + very large random number
                            # Verify this last resort ID is unique before using it
                            last_resort_id = None
                            for final_attempt in range(5):  # Try up to 5 times for last resort
                                candidate_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                                async with aiosqlite.connect(DB_PATH) as db:
                                    cur = await db.execute(
                                        "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                        (guild.id, candidate_id)
                                    )
                                    exists = await cur.fetchone()
                                if not exists:
                                    last_resort_id = candidate_id
                                    break
                            # If still no unique ID after 5 attempts, use the candidate anyway (very unlikely collision)
                            case_id = last_resort_id or f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                
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
        
        # Handle ApplicationResponseModal submissions
        if cid and cid.startswith("application_response_"):
            # Extract application_id and question_id from custom_id
            # Format: application_response_{application_id}_{question_id}
            parts = cid.replace("application_response_", "").split("_")
            if len(parts) >= 2:
                application_id = int(parts[0])
                question_id = int(parts[1])
                
                if not interaction.response.is_done():
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                        pass
                
                # Extract response from interaction data
                components = interaction.data.get("components", [])
                response_text = ""
                
                for component in components:
                    components_list = component.get("components", [])
                    for comp in components_list:
                        comp_id = comp.get("custom_id", "")
                        value = comp.get("value", "")
                        if comp_id == "response":
                            response_text = value
                
                if not response_text.strip():
                    await interaction.followup.send("Response cannot be empty.", ephemeral=True)
                    return
                
                # Save response
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT INTO application_responses (application_id, question_id, response_text)
                        VALUES (?, ?, ?)
                    """, (application_id, question_id, response_text))
                    
                    # Update current_question_index
                    await db.execute("""
                        UPDATE applications
                        SET current_question_index = current_question_index + 1
                        WHERE id = ?
                    """, (application_id,))
                    await db.commit()
                    
                    # Get guild_id and user_id
                    cur = await db.execute("""
                        SELECT guild_id, user_id FROM applications WHERE id = ?
                    """, (application_id,))
                    row = await cur.fetchone()
                
                if row:
                    guild_id, user_id = row[0], row[1]
                    
                    # Send next question or submit application
                    from commands.applications.application import send_next_question
                    await send_next_question(bot, guild_id, user_id, application_id)
                    
                    await interaction.followup.send("Response saved! Check your DMs for the next question.", ephemeral=True)
                else:
                    await interaction.followup.send("Application not found.", ephemeral=True)
            return
        
        # Handle ApplicationQuestionModal submissions
        if cid and cid.startswith("application_question_"):
            # This is handled in the modal's on_submit, but we can add logging here if needed
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    pass
            return
        
        # Handle ApplicationRejectModal submissions
        if cid and cid.startswith("application_reject_"):
            # This is handled in the modal's on_submit
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
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
                            # Fallback: use full timestamp with nanoseconds simulation
                            import time
                            fallback_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"
                            
                            # Verify fallback ID is unique before using it
                            async with aiosqlite.connect(DB_PATH) as db:
                                cur = await db.execute(
                                    "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                    (guild.id, fallback_id)
                                )
                                fallback_exists = await cur.fetchone()
                            
                            if not fallback_exists:
                                case_id = fallback_id
                            else:
                                # Last resort: use timestamp + user_id + very large random number
                                # Verify this last resort ID is unique before using it
                                last_resort_id = None
                                for final_attempt in range(5):  # Try up to 5 times for last resort
                                    candidate_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                                    async with aiosqlite.connect(DB_PATH) as db:
                                        cur = await db.execute(
                                            "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                            (guild.id, candidate_id)
                                        )
                                        exists = await cur.fetchone()
                                    if not exists:
                                        last_resort_id = candidate_id
                                        break
                                # If still no unique ID after 5 attempts, use the candidate anyway (very unlikely collision)
                                case_id = last_resort_id or f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                    
                    created_iso = created.isoformat()

                    # Check for duplicates
                    async with aiosqlite.connect(DB_PATH) as db:
                        # Convert ISO 8601 datetime to SQLite datetime format for proper comparison
                        check_cur = await db.execute(
                            "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND datetime(created_at) > datetime('now', '-5 seconds')",
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
                            client=bot,
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
                    return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)

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
                    # Use followup for set_status and message (don't call response methods after defer)
                    await view.set_status(interaction, "ACKNOWLEDGED", bot=bot)
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
                    await view.set_status(interaction, "RESOLVED", bot=bot)
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
                    await view.set_status(interaction, "REJECTED", bot=bot)
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

        # Giveaways: Enter/Leave
        if cid and cid.startswith("giveaway:"):
            action = cid.split(":")[-1]
            if action in ["enter", "leave"]:
                # Get giveaway ID from message
                if not interaction.message:
                    return
                
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT id FROM giveaways WHERE guild_id = ? AND message_id = ? AND ended = 0
                    """, (interaction.guild.id, interaction.message.id))
                    row = await cur.fetchone()
                
                if not row:
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "❌ Giveaway Not Found",
                            "This giveaway no longer exists or has ended.",
                            color=discord.Color.red(),
                            client=bot,
                        ),
                        ephemeral=True
                    )
                
                giveaway_id = row[0]
                from views import GiveawayView
                view = GiveawayView(giveaway_id)
                
                if action == "enter":
                    await view.enter_giveaway(interaction, None)
                elif action == "leave":
                    await view.leave_giveaway(interaction, None)
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
        
        # Trading posts: mark as sold or delete
        if cid.startswith("trade:"):
            # trade:{listing_id}:{action}
            parts = cid.split(":")
            if len(parts) == 3:
                _, listing_id_str, action = parts
                try:
                    listing_id = int(listing_id_str)
                except ValueError:
                    return
                
                # Get listing info
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT user_id, status FROM trading_posts WHERE id = ?
                    """, (listing_id,))
                    row = await cur.fetchone()
                
                if not row:
                    return await interaction.response.send_message("Listing not found.", ephemeral=True)
                
                owner_id, status = row[0], row[1]
                
                # Check if user is the owner
                if interaction.user.id != owner_id:
                    return await interaction.response.send_message("Only the listing owner can manage this listing.", ephemeral=True)
                
                # Check if already sold/deleted
                if status != "ACTIVE":
                    return await interaction.response.send_message("This listing is no longer active.", ephemeral=True)
                
                await interaction.response.defer(ephemeral=True)
                
                from views import TradingPostView
                view = TradingPostView(listing_id, owner_id)
                
                if action == "sold":
                    await view.mark_sold_button(interaction)
                elif action == "delete":
                    await view.delete_button(interaction)
                return
        
        # Applications: approve or reject
        if cid.startswith("application:"):
            # application:{application_id}:{action}
            parts = cid.split(":")
            if len(parts) == 3:
                _, application_id_str, action = parts
                try:
                    application_id = int(application_id_str)
                except ValueError:
                    return
                
                if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                    return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)
                
                await interaction.response.defer(ephemeral=True)
                
                from views import ApplicationManageView
                view = ApplicationManageView(application_id)
                
                if action == "approve":
                    await view.approve_button(interaction)
                elif action == "reject":
                    await view.reject_button(interaction)
                return

    except Exception as e:
        # Last-resort error handler - only for component/modal interactions
        # Do NOT handle errors for application commands - let discord.py handle them
        if interaction.type == discord.InteractionType.application_command:
            # Already handled (command usage tracking), just return silently
            # discord.py will handle any actual command errors
            return
        
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
# Background tasks are now in tasks.py and started via setup_tasks() in on_ready


# --------------------- Economy Commands ---------------------
# Economy commands are now loaded from commands/economy/ folder via load_all_commands()


# --------------------- Update Log Functions ---------------------
def calculate_feature_hash(bot) -> str:
    """Calculate a hash of all registered commands and key bot files to detect changes."""
    import hashlib
    import os
    commands_list = []
    
    # Get all commands (both global and guild-specific)
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            commands_list = sorted([cmd.name for cmd in bot.tree.get_commands(guild=guild)])
        else:
            commands_list = sorted([cmd.name for cmd in bot.tree.get_commands(guild=None)])
        logger.info(f"[version] Calculated hash from {len(commands_list)} commands: {', '.join(commands_list[:10])}{'...' if len(commands_list) > 10 else ''}")
    except Exception as e:
        logger.error(f"[version] Error getting commands: {e}", exc_info=True)
        return ""
    
    # Create hash from sorted command list
    commands_str = ",".join(commands_list)
    
    # Also include hash of key bot files to detect code changes
    # This ensures version updates even when code changes without command changes
    file_hashes = []
    key_files = ["bot.py", "database.py", "warframe_api.py", "tasks.py", "utils.py", "views.py"]
    
    # Get the directory where bot.py is located
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    
    for filename in key_files:
        filepath = os.path.join(bot_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'rb') as f:
                    file_content = f.read()
                    file_hash = hashlib.md5(file_content).hexdigest()[:8]  # First 8 chars
                    file_hashes.append(f"{filename}:{file_hash}")
                    logger.debug(f"[version] Hashed {filename}: {file_hash}")
            except Exception as e:
                logger.warning(f"[version] Could not hash {filename}: {e}")
        else:
            logger.debug(f"[version] File not found for hashing: {filepath}")
    
    # Combine commands and file hashes
    combined_str = commands_str + "|" + "|".join(file_hashes)
    hash_value = hashlib.md5(combined_str.encode()).hexdigest()
    logger.info(f"[version] Feature hash: {hash_value[:8]}... (from {len(commands_list)} commands + {len(file_hashes)} files)")
    return hash_value


async def detect_and_update_version(bot) -> Tuple[str, list]:
    """
    Detect if features have changed and auto-increment version.
    Also checks if BOT_VERSION env var has changed.
    Returns: (version, list of changes)
    """
    current_hash = calculate_feature_hash(bot)
    
    # Get current commands list for comparison
    current_commands = set()
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            current_commands = set(cmd.name for cmd in bot.tree.get_commands(guild=guild))
        else:
            current_commands = set(cmd.name for cmd in bot.tree.get_commands(guild=None))
    except Exception:
        pass
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get stored version info and previous commands
        cur = await db.execute("""
            SELECT current_version, feature_hash, previous_commands FROM bot_version_tracking WHERE id = 1
        """)
        row = await cur.fetchone()
        
        if not row:
            # First time - initialize with version 1.2.0
            new_version = "1.2.0"
            changes = ["Initial bot version"]
            if current_commands:
                changes.append(f"**Commands:** {', '.join(sorted(current_commands))}")
            logger.info(f"[version] First run detected, initializing with version {new_version}")
            # Store current commands as previous_commands for next comparison
            current_commands_str = ",".join(sorted(current_commands)) if current_commands else ""
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (new_version, current_hash, datetime.now(timezone.utc).isoformat(), current_commands_str))
            await db.commit()
            
            # Verify the version was stored correctly
            verify_cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
            verify_row = await verify_cur.fetchone()
            if verify_row and verify_row[0] == new_version:
                logger.info(f"[version] ✅ Version {new_version} successfully stored and verified in database")
            else:
                logger.error(f"[version] ❌ Version storage verification failed! Expected {new_version}, got {verify_row}")
            
            return new_version, changes
        else:
            stored_version = row[0]
            stored_hash = row[1] if len(row) > 1 else ""
            previous_commands_str = row[2] if len(row) > 2 and row[2] else None
            
            # Reset version to 1.2.0 if stored version is less than 1.2.0
            try:
                version_parts = stored_version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    if major < 1 or (major == 1 and minor < 2):
                        logger.info(f"[version] Resetting version from {stored_version} to 1.2.0")
                        stored_version = "1.2.0"
                        # Update stored version
                        await db.execute("""
                            UPDATE bot_version_tracking 
                            SET current_version = ? 
                            WHERE id = 1
                        """, (stored_version,))
                        await db.commit()
            except (ValueError, IndexError):
                # Invalid version format, reset to 1.2.0
                logger.info(f"[version] Invalid version format {stored_version}, resetting to 1.2.0")
                stored_version = "1.2.0"
                await db.execute("""
                    UPDATE bot_version_tracking 
                    SET current_version = ? 
                    WHERE id = 1
                """, (stored_version,))
                await db.commit()
            
            logger.info(f"[version] Loaded stored version: {stored_version}, hash: {stored_hash[:8] if stored_hash else 'empty'}...")
            
            # Get previous commands from stored data (these are the commands from the LAST version)
            previous_commands = set()
            if previous_commands_str:
                try:
                    previous_commands = set(previous_commands_str.split(",")) if previous_commands_str else set()
                    logger.info(f"[version] Previous commands loaded: {len(previous_commands)} commands")
                except Exception as e:
                    logger.warning(f"[version] Error parsing previous commands: {e}")
                    previous_commands = set()
            else:
                logger.info(f"[version] No previous commands stored (first change detection)")
            
            # Note: We ignore BOT_VERSION env var for automatic versioning
            # It's only used as a fallback if no version is stored yet
            # This ensures automatic versioning works correctly
            
            # If hash hasn't changed, no update needed - return stored version with no changes
            if stored_hash == current_hash:
                logger.info(f"[version] No changes detected (hash: {current_hash[:8] if current_hash else 'empty'}...), keeping version {stored_version}")
                # Return stored version with empty changes list - this means no update needed
                return stored_version, []
            
            # Hash changed - detect what changed
            logger.info(f"[version] Hash changed from {stored_hash[:8] if stored_hash else 'empty'}... to {current_hash[:8]}...")
            changes = []
            
            # previous_commands is already loaded from the row above
            # Compare commands to detect additions and removals
            logger.info(f"[version] Comparing commands: previous={len(previous_commands)}, current={len(current_commands)}")
            added_commands = current_commands - previous_commands
            removed_commands = previous_commands - current_commands
            
            logger.info(f"[version] Command changes detected: +{len(added_commands)} added, -{len(removed_commands)} removed")
            
            if added_commands:
                changes.append(f"✅ **Added {len(added_commands)} command(s):** {', '.join(sorted(added_commands))}")
            if removed_commands:
                changes.append(f"❌ **Removed {len(removed_commands)} command(s):** {', '.join(sorted(removed_commands))}")
            if not added_commands and not removed_commands and previous_commands:
                # Commands exist but changed in some way (maybe internal changes)
                changes.append("🔄 **Internal updates:** Commands or features have been modified")
            elif not previous_commands:
                # First time detecting changes - don't show all commands, just note it's the first change
                changes.append("🚀 **First feature update:** Bot features have been updated")
            
            # Commands have changed - increment version based on change type
            try:
                # Parse version (format: MAJOR.MINOR.PATCH)
                version_parts = stored_version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    patch = int(version_parts[2]) if len(version_parts) > 2 else 0
                    
                    # Determine if this is a "big" change (commands added/removed) or "small" change (internal updates only)
                    # Check if sets are non-empty (len() > 0) rather than using bool() on sets
                    has_added = len(added_commands) > 0
                    has_removed = len(removed_commands) > 0
                    is_big_change = has_added or has_removed
                    
                    logger.info(f"[version] Change detection: added={has_added} ({len(added_commands)}), removed={has_removed} ({len(removed_commands)}), is_big={is_big_change}")
                    
                    if is_big_change:
                        # Big change: increment minor version (1.7.0 → 1.8.0)
                        minor += 1
                        patch = 0  # Reset patch
                        logger.info(f"[version] Big change detected (commands added/removed), incrementing minor version")
                    else:
                        # Small change: increment patch version (1.7.0 → 1.7.1)
                        patch += 1
                        logger.info(f"[version] Small change detected (internal updates only), incrementing patch version")
                    
                    new_version = f"{major}.{minor}.{patch}"
                else:
                    # Fallback: start at 1.2.0
                    new_version = "1.2.0"
            except (ValueError, IndexError):
                # Invalid version format, start at 1.2.0
                new_version = "1.2.0"
            
            # Update stored version, hash, and store CURRENT commands as previous_commands for next comparison
            current_commands_str = ",".join(sorted(current_commands)) if current_commands else ""
            await db.execute("""
                INSERT OR REPLACE INTO bot_version_tracking (id, current_version, feature_hash, last_updated, previous_commands)
                VALUES (1, ?, ?, ?, ?)
            """, (new_version, current_hash, datetime.now(timezone.utc).isoformat(), current_commands_str))
            await db.commit()
            
            # Verify the version was stored correctly
            verify_cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
            verify_row = await verify_cur.fetchone()
            if verify_row and verify_row[0] == new_version:
                logger.info(f"[version] ✅ Version {new_version} successfully stored and verified in database (from {stored_version})")
            else:
                logger.error(f"[version] ❌ Version storage verification failed! Expected {new_version}, got {verify_row}")
            
            logger.info(f"[version] Version incremented to {new_version} (from {stored_version}), stored {len(current_commands)} commands as previous_commands")
            return new_version, changes


async def check_and_post_updates(bot):
    """Check if bot version has changed and post update logs automatically."""
    logger.info("[update_log] ========== Starting automatic update check ==========")
    
    # First, detect if version should be auto-updated
    detected_version, changes = await detect_and_update_version(bot)
    logger.info(f"[update_log] Version detection result: version={detected_version}, changes={len(changes) if changes else 0}")
    if changes:
        logger.info(f"[update_log] Changes detected: {changes}")
    
    # If no changes detected, don't post an update (version persists, no need to post)
    if not changes:
        logger.info(f"[update_log] No changes detected, version remains at {detected_version}, skipping update post")
        return
    
    # Use detected version (or fallback to env version)
    version_to_use = detected_version if detected_version else BOT_VERSION
    
    if not version_to_use:
        logger.warning("[update_log] No version set, skipping update check")
        return  # No version set, skip
    
    logger.info(f"[update_log] Version changed to {version_to_use}, posting update with {len(changes)} change(s)")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get all guilds with update log channels configured
        cur = await db.execute("""
            SELECT guild_id, channel_id FROM update_log_settings WHERE channel_id IS NOT NULL
        """)
        guilds_with_logs = await cur.fetchall()
        logger.info(f"[update_log] Query result: {guilds_with_logs}")
    
    if not guilds_with_logs:
        logger.warning("[update_log] ⚠️ No update log channels configured in database! Use /update_log_setup to configure a channel.")
        return  # No update log channels configured
    
    logger.info(f"[update_log] Found {len(guilds_with_logs)} guild(s) with update log channels configured")
    
    for guild_id, channel_id in guilds_with_logs:
        try:
            guild = bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"[update_log] Guild {guild_id} not found, skipping")
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                logger.warning(f"[update_log] Channel {channel_id} not found in guild {guild.name}, skipping")
                continue
            
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"[update_log] Channel {channel_id} in {guild.name} is not a text channel, skipping")
                continue
            
            # Verify bot has permission to send messages in this channel
            if not bot.user:
                logger.warning(f"[update_log] bot.user is None, skipping guild {guild.name}")
                continue
            
            bot_member = guild.get_member(bot.user.id)
            if not bot_member:
                logger.warning(f"[update_log] Bot member not found in guild {guild.name}, skipping")
                continue
            
            permissions = channel.permissions_for(bot_member)
            if not permissions.send_messages or not permissions.embed_links:
                logger.warning(f"[update_log] Bot lacks permissions (send_messages={permissions.send_messages}, embed_links={permissions.embed_links}) in {guild.name} (#{channel.name}), skipping")
                continue
            
            logger.info(f"[update_log] Verified channel {guild.name} (#{channel.name}) - has permissions, proceeding...")
            
            # Check if this version has already been posted
            # BUT: If changes were just detected (meaning version was just incremented), post anyway
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT 1 FROM update_log_posted_versions 
                    WHERE guild_id = ? AND version = ?
                """, (guild_id, version_to_use))
                already_posted = await cur.fetchone()
            
            if already_posted:
                if changes:
                    # Version was posted before, but changes were just detected - this means version was just incremented
                    # Post it again to notify about the new version
                    logger.info(f"[update_log] ⚠️ Version {version_to_use} was posted before, but NEW CHANGES detected - will post update anyway")
                else:
                    # Already posted and no new changes - skip
                    logger.info(f"[update_log] Version {version_to_use} already posted to {guild.name} (#{channel.name}) and no new changes, skipping")
                    continue
            else:
                logger.info(f"[update_log] Version {version_to_use} not yet posted to {guild.name} (#{channel.name}), will post now")
            
            logger.info(f"[update_log] Version {version_to_use} not yet posted to {guild.name} (#{channel.name}), posting now...")
            
            # Build git-style commit summary
            # Parse changes into categories
            added_commands = []
            removed_commands = []
            other_changes = []
            
            for change in changes:
                if "✅ **Added" in change or "Added" in change:
                    # Extract command names
                    if "command(s):" in change:
                        cmd_list = change.split("command(s):")[-1].strip()
                        added_commands.extend([cmd.strip() for cmd in cmd_list.split(",")])
                elif "❌ **Removed" in change or "Removed" in change:
                    if "command(s):" in change:
                        cmd_list = change.split("command(s):")[-1].strip()
                        removed_commands.extend([cmd.strip() for cmd in cmd_list.split(",")])
                else:
                    other_changes.append(change)
            
            # Build summary (like git commit message)
            summary_parts = []
            
            # Main summary from BOT_CHANGELOG if available
            if BOT_CHANGELOG:
                summary_parts.append(f"**Summary:**\n{BOT_CHANGELOG}")
            
            # Build changes summary
            changes_summary = []
            
            if added_commands:
                changes_summary.append(f"**Added ({len(added_commands)}):**\n" + "\n".join([f"  + `{cmd}`" for cmd in sorted(added_commands)]))
            
            if removed_commands:
                changes_summary.append(f"**Removed ({len(removed_commands)}):**\n" + "\n".join([f"  - `{cmd}`" for cmd in sorted(removed_commands)]))
            
            if other_changes:
                # Clean up other changes (remove markdown formatting for cleaner display)
                for change in other_changes:
                    clean_change = change.replace("**", "").replace("🔄", "").replace("🚀", "").strip()
                    if clean_change:
                        changes_summary.append(f"**Modified:**\n  {clean_change}")
            
            # Combine summary
            if summary_parts:
                description = "\n\n".join(summary_parts)
            else:
                description = f"**Update Summary:**\nBot updated to version {version_to_use}"
            
            if changes_summary:
                description += "\n\n" + "\n\n".join(changes_summary)
            
            # If no changes detected but we're posting (shouldn't happen, but safety check)
            if not changes_summary and not BOT_CHANGELOG:
                description = f"Bot has been updated to version {version_to_use}."
                logger.warning(f"[update_log] No changelog or changes detected for version {version_to_use}, posting generic message")
            
            # Post the update
            title = f"Bot Updated to v{version_to_use}"
            
            fields = [
                ("Changelog", description, False),
                ("Version", version_to_use, True),
                ("Date", f"<t:{int(datetime.now(timezone.utc).timestamp())}:F>", True),
            ]
            
            from utils import obsidian_embed
            embed = obsidian_embed(
                f"🔔 Bot Update: {title}",
                "",
                color=discord.Color.blue(),
                fields=fields,
                client=bot,
            )
            embed.timestamp = datetime.now(timezone.utc)
            
            try:
                logger.info(f"[update_log] Attempting to send embed to {guild.name} (#{channel.name})...")
                await channel.send(embed=embed)
                logger.info(f"[update_log] ✅ Embed sent successfully!")
                
                # Mark this version as posted for this guild
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO update_log_posted_versions (guild_id, version, posted_at)
                        VALUES (?, ?, ?)
                    """, (guild_id, version_to_use, datetime.now(timezone.utc).isoformat()))
                    await db.commit()
                    logger.info(f"[update_log] ✅ Marked version {version_to_use} as posted for guild {guild_id}")
                
                logger.info(f"[update_log] ✅✅✅ Successfully posted automatic update v{version_to_use} to {guild.name} (#{channel.name})")
            except discord.Forbidden as e:
                logger.error(f"[update_log] ❌ No permission to post in {guild.name} (#{channel.name}): {e}")
            except discord.NotFound as e:
                logger.error(f"[update_log] ❌ Channel not found in {guild.name} (channel_id: {channel_id}): {e}")
            except discord.HTTPException as e:
                logger.error(f"[update_log] ❌ HTTP error posting to {guild.name} (#{channel.name}): {e}")
            except Exception as e:
                logger.error(f"[update_log] ❌ Unexpected error posting update to {guild.name} (#{channel.name}): {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[update_log] ❌ Error processing update for guild {guild_id}: {e}", exc_info=True)
    
    logger.info("[update_log] ========== Automatic update check completed ==========")


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
    
    # Set custom status
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name="Over The Land of The Obsidian Oath Legion"
    )
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"[ready] Status set: Watching Over The Land of The Obsidian Oath Legion")

    # Ensure channels + join-to-create exist on startup (covers restarts)
    for g in bot.guilds:
        try:
            await ensure_core_channels(g)
            await ensure_join_to_create_channel(g)
        except Exception as e:
            print(f"[startup] Ensure failed in {g.name}: {e}")

    # Setup background tasks
    try:
        tasks_dict = setup_tasks(bot)
        print(f"[ready] Background tasks initialized: {len(tasks_dict)} tasks")
    except Exception as e:
        print(f"[ready] ERROR: Failed to setup background tasks: {e}")
        import traceback
        traceback.print_exc()
    
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

    # Re-register suggestion views for pending suggestions
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT id FROM suggestions WHERE guild_id=? AND status='PENDING'",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (suggestion_id,) in rows:
                try:
                    from commands.suggestions.manage_suggestions import SuggestionView
                    bot.add_view(SuggestionView(int(suggestion_id)))
                except Exception:
                    pass
    
    # Re-register application views for pending applications
    from views import ApplicationManageView
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT id FROM applications WHERE guild_id=? AND status='PENDING'",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (application_id,) in rows:
                try:
                    bot.add_view(ApplicationManageView(int(application_id)))
                except Exception:
                    pass
    
    # Re-register giveaway views for active giveaways
    from views import GiveawayView
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id FROM giveaways WHERE ended = 0
        """)
        active_giveaways = await cur.fetchall()
    
    for (giveaway_id,) in active_giveaways:
        try:
            bot.add_view(GiveawayView(giveaway_id))
        except Exception as e:
            logger.debug(f"[ready] Error re-registering giveaway view {giveaway_id}: {e}")
    
    # Re-register trading post views for active listings
    from views import TradingPostView
    async with aiosqlite.connect(DB_PATH) as db:
        for g in bot.guilds:
            cur = await db.execute(
                "SELECT id, user_id FROM trading_posts WHERE guild_id=? AND status='ACTIVE'",
                (g.id,),
            )
            rows = await cur.fetchall()
            for (listing_id, user_id) in rows:
                try:
                    bot.add_view(TradingPostView(int(listing_id), int(user_id)))
                except Exception:
                    pass
    
    # Verify update log settings persistence
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT guild_id, channel_id FROM update_log_settings WHERE channel_id IS NOT NULL
        """)
        settings = await cur.fetchall()
        if settings:
            logger.info(f"[ready] Loaded {len(settings)} update log channel setting(s) from database")
            for guild_id, channel_id in settings:
                guild = bot.get_guild(guild_id)
                if guild:
                    channel = guild.get_channel(channel_id)
                    if channel:
                        logger.info(f"[ready] Update log channel configured: {guild.name} -> #{channel.name}")
                    else:
                        logger.warning(f"[ready] Update log channel not found: guild {guild.name}, channel_id {channel_id}")
        else:
            logger.info("[ready] No update log channels configured")
        
        # Verify version tracking exists
        cur = await db.execute("SELECT current_version FROM bot_version_tracking WHERE id = 1")
        version_row = await cur.fetchone()
        if version_row:
            logger.info(f"[ready] Bot version tracking loaded: {version_row[0]}")
        else:
            logger.info("[ready] No version tracking found (will be created on first update check)")
    
    # Initialize achievement definitions
    try:
        from database import initialize_achievement_definitions
        await initialize_achievement_definitions()
        logger.info("[ready] Achievement definitions initialized")
    except Exception as e:
        logger.error(f"[ready] Error initializing achievements: {e}", exc_info=True)
    
    # Wait a bit for commands to fully sync, then check and post automatic update logs
    try:
        logger.info("[ready] Waiting for commands to sync, then checking for automatic updates...")
        await asyncio.sleep(5)  # Give commands more time to fully register and sync with Discord
        logger.info("[ready] Starting update check...")
        await check_and_post_updates(bot)
        logger.info("[ready] Automatic update check completed")
    except Exception as e:
        logger.error(f"[ready] Error during automatic update check: {e}", exc_info=True)
    
    # Re-register reaction roles for all messages
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT DISTINCT message_id, channel_id FROM reaction_roles
        """)
        reaction_messages = await cur.fetchall()
    
    for message_id, channel_id in reaction_messages:
        try:
            channel = bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(message_id)
                    # Get all reactions for this message
                    async with aiosqlite.connect(DB_PATH) as db2:
                        cur2 = await db2.execute("""
                            SELECT emoji FROM reaction_roles
                            WHERE message_id = ? AND channel_id = ?
                        """, (message_id, channel_id))
                        emojis = await cur2.fetchall()
                    
                    # Re-add reactions if they're missing
                    for (emoji_str,) in emojis:
                        try:
                            # Check if reaction already exists
                            if not any(str(r.emoji) == emoji_str for r in message.reactions):
                                await message.add_reaction(emoji_str)
                        except Exception as e:
                            logger.debug(f"[ready] Could not re-add reaction {emoji_str} to message {message_id}: {e}")
                except discord.NotFound:
                    logger.debug(f"[ready] Reaction role message {message_id} not found, skipping")
                except Exception as e:
                    logger.debug(f"[ready] Error re-registering reaction roles for message {message_id}: {e}")
        except Exception as e:
            logger.debug(f"[ready] Error processing reaction role message {message_id}: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    """Send welcome message when a member joins."""
    # Check for join anniversary milestones (check existing join date)
    from database import check_and_record_milestone, check_and_unlock_achievement, initialize_achievement_definitions
    await initialize_achievement_definitions()
    
    # Get member's join date
    join_date = member.joined_at or now_utc()
    years_in_server = (now_utc() - join_date.replace(tzinfo=timezone.utc)).days // 365
    
    # Check anniversary milestones
    if years_in_server >= 1:
        milestone_achieved = await check_and_record_milestone(
            member.guild.id, member.id, "join_anniversary", years_in_server
        )
        if milestone_achieved and years_in_server <= 2:  # Only for 1-2 year anniversaries
            achievement_id = f"join_anniversary_{years_in_server}"
            await check_and_unlock_achievement(member.guild.id, member.id, achievement_id, bot)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id, message, enabled FROM welcome_settings
            WHERE guild_id = ? AND enabled = 1
        """, (member.guild.id,))
        row = await cur.fetchone()
    
    if not row or not row[0]:  # No channel set or disabled
        return
    
    channel_id, message_template, enabled = row
    if not enabled:
        return
    
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    # Format message
    formatted_message = message_template.replace("{user}", member.mention)
    formatted_message = formatted_message.replace("{server}", member.guild.name)
    formatted_message = formatted_message.replace("{member_count}", str(member.guild.member_count))
    
    try:
        await channel.send(formatted_message)
    except Exception as e:
        logger.error(f"[welcome] Error sending welcome message: {e}")


@bot.event
async def on_member_remove(member: discord.Member):
    """Send leave message and log kicks."""
    # Check if it was a kick (audit log)
    was_kicked = False
    try:
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                was_kicked = True
                # Log kick
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT channel_id FROM log_channels
                        WHERE guild_id=? AND log_type='member_kick' AND enabled=1
                    """, (member.guild.id,))
                    row = await cur.fetchone()
                
                if row:
                    log_channel = member.guild.get_channel(row[0])
                    if isinstance(log_channel, discord.TextChannel):
                        try:
                            reason = entry.reason or "No reason provided"
                            embed = obsidian_embed(
                                "👢 Member Kicked",
                                f"**User:** {member.mention} ({member})\n"
                                f"**User ID:** {member.id}\n"
                                f"**Reason:** {reason}",
                                color=discord.Color.orange(),
                                client=bot,
                            )
                            await log_channel.send(embed=embed)
                        except Exception as e:
                            logger.error(f"[logging] Error logging member kick: {e}")
                break
    except Exception:
        pass
    
    # Original leave message code
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id, message, enabled FROM leave_settings
            WHERE guild_id = ? AND enabled = 1
        """, (member.guild.id,))
        row = await cur.fetchone()
    
    if not row or not row[0]:  # No channel set or disabled
        return
    
    channel_id, message_template, enabled = row
    if not enabled:
        return
    
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    # Format message
    formatted_message = message_template.replace("{user}", str(member))
    formatted_message = formatted_message.replace("{server}", member.guild.name)
    formatted_message = formatted_message.replace("{member_count}", str(member.guild.member_count))
    
    try:
        await channel.send(formatted_message)
    except Exception as e:
        logger.error(f"[leave] Error sending leave message: {e}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Handle reaction adds for starboard and other features."""
    # Starboard handling
    if payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
        if guild:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT channel_id, threshold, emoji FROM starboard_settings WHERE guild_id=?
                """, (guild.id,))
                row = await cur.fetchone()
                
                if row:
                    starboard_channel_id, threshold, emoji = row
                    starboard_channel = guild.get_channel(starboard_channel_id)
                    
                    if starboard_channel and str(payload.emoji) == emoji:
                        try:
                            channel = guild.get_channel(payload.channel_id)
                            if channel and isinstance(channel, discord.TextChannel):
                                message = await channel.fetch_message(payload.message_id)
                                
                                # Count reactions
                                reaction = discord.utils.get(message.reactions, emoji=emoji)
                                if reaction and reaction.count >= threshold:
                                    # Check if already in starboard
                                    cur = await db.execute("""
                                        SELECT starboard_message_id, stars FROM starboard_messages
                                        WHERE guild_id=? AND original_message_id=?
                                    """, (guild.id, message.id))
                                    existing = await cur.fetchone()
                                    
                                    if existing:
                                        # Update existing starboard message
                                        starboard_msg_id, old_stars = existing
                                        if reaction.count != old_stars:
                                            try:
                                                starboard_msg = await starboard_channel.fetch_message(starboard_msg_id)
                                                embed = starboard_msg.embeds[0] if starboard_msg.embeds else None
                                                if embed:
                                                    embed.set_footer(text=f"{reaction.count} {emoji} | {message.channel.mention}")
                                                    await starboard_msg.edit(embed=embed)
                                                
                                                await db.execute("""
                                                    UPDATE starboard_messages SET stars=?
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (reaction.count, guild.id, message.id))
                                                await db.commit()
                                            except discord.NotFound:
                                                # Starboard message deleted, remove from DB
                                                await db.execute("""
                                                    DELETE FROM starboard_messages
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (guild.id, message.id))
                                                await db.commit()
                                    else:
                                        # Create new starboard message
                                        embed = obsidian_embed(
                                            f"{emoji} {message.author.display_name}",
                                            message.content or "*No content*",
                                            color=discord.Color.gold(),
                                            client=bot,
                                        )
                                        embed.set_footer(text=f"{reaction.count} {emoji} | {message.channel.mention}")
                                        embed.timestamp = message.created_at
                                        
                                        if message.attachments:
                                            embed.set_image(url=message.attachments[0].url)
                                        
                                        starboard_msg = await starboard_channel.send(embed=embed)
                                        
                                        # Store in database
                                        await db.execute("""
                                            INSERT INTO starboard_messages (guild_id, original_message_id, starboard_message_id, stars)
                                            VALUES (?, ?, ?, ?)
                                        """, (guild.id, message.id, starboard_msg.id, reaction.count))
                                        await db.commit()
                        except Exception as e:
                            logger.error(f"Error handling starboard reaction: {e}", exc_info=True)
    
    # Reaction role handling (only if not a bot reaction)
    if payload.guild_id and not (payload.member and payload.member.bot):
        # Ignore bot reactions
        if payload.member and payload.member.bot:
            return
    
    # Check if this is a reaction role message
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (payload.guild_id, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    # Get member (might be None if user left)
    member = payload.member
    if not member:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
    
    # Check bot permissions
    if not guild.me.guild_permissions.manage_roles:
        return
    
    # Check if bot's role is high enough
    if guild.me.top_role <= role:
        return
    
    # Add role
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Reaction role")
            logger.info(f"[reaction_role] Added role {role.name} to {member} via reaction {payload.emoji}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to add role {role.name} to {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error adding role: {e}")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Handle reaction role removal."""
    # Check if this is a reaction role message
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (payload.guild_id, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    # Get member
    try:
        member = await guild.fetch_member(payload.user_id)
    except discord.NotFound:
        return
    
    # Check bot permissions
    if not guild.me.guild_permissions.manage_roles:
        return
    
    # Check if bot's role is high enough
    if guild.me.top_role <= role:
        return
    
    # Remove role
    try:
        if role in member.roles:
            await member.remove_roles(role, reason="Reaction role removed")
            logger.info(f"[reaction_role] Removed role {role.name} from {member} via reaction removal {payload.emoji}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to remove role {role.name} from {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error removing role: {e}")


@bot.event
async def on_message_delete(message: discord.Message):
    """Log deleted messages."""
    if not message.guild or message.author.bot:
        return
    
    # Store deleted message
    attachments_json = None
    if message.attachments:
        attachments_json = json.dumps([{"url": att.url, "filename": att.filename} for att in message.attachments])
    
    embeds_json = None
    if message.embeds:
        embeds_json = json.dumps([embed.to_dict() for embed in message.embeds])
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO deleted_messages 
            (guild_id, channel_id, message_id, user_id, content, author_name, author_avatar, attachments, embeds, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.guild.id,
            message.channel.id,
            message.id,
            message.author.id,
            message.content[:2000] if message.content else None,
            str(message.author),
            str(message.author.display_avatar.url) if message.author.display_avatar else None,
            attachments_json,
            embeds_json,
            now_utc().isoformat()
        ))
        await db.commit()
    
    # Send to log channel if configured
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_delete' AND enabled=1
        """, (message.guild.id,))
        row = await cur.fetchone()
    
    if row:
        log_channel = message.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "🗑️ Message Deleted",
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Author:** {message.author.mention} ({message.author})\n"
                    f"**Content:** {message.content[:1000] if message.content else '*No content*'}",
                    color=discord.Color.red(),
                    client=bot,
                )
                if message.attachments:
                    embed.add_field(name="Attachments", value=f"{len(message.attachments)} attachment(s)", inline=False)
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging message delete: {e}")


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """Log edited messages."""
    if not after.guild or after.author.bot or before.content == after.content:
        return
    
    # Store edit
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO edited_messages 
            (guild_id, channel_id, message_id, user_id, old_content, new_content, author_name, edited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            after.guild.id,
            after.channel.id,
            after.id,
            after.author.id,
            before.content[:2000] if before.content else None,
            after.content[:2000] if after.content else None,
            str(after.author),
            now_utc().isoformat()
        ))
        await db.commit()
    
    # Send to log channel if configured
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_edit' AND enabled=1
        """, (after.guild.id,))
        row = await cur.fetchone()
    
    if row:
        log_channel = after.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "✏️ Message Edited",
                    f"**Channel:** {after.channel.mention}\n"
                    f"**Author:** {after.author.mention} ({after.author})\n"
                    f"**Before:** {before.content[:500] if before.content else '*No content*'}\n"
                    f"**After:** {after.content[:500] if after.content else '*No content*'}\n"
                    f"[Jump to Message]({after.jump_url})",
                    color=discord.Color.orange(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging message edit: {e}")


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    """Log member bans."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='member_ban' AND enabled=1
        """, (guild.id,))
        row = await cur.fetchone()
    
    if row:
        log_channel = guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                # Try to get audit log entry for reason
                reason = "No reason provided"
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                    if entry.target and entry.target.id == user.id:
                        reason = entry.reason or "No reason provided"
                        break
                
                embed = obsidian_embed(
                    "🔨 Member Banned",
                    f"**User:** {user.mention} ({user})\n"
                    f"**User ID:** {user.id}\n"
                    f"**Reason:** {reason}",
                    color=discord.Color.red(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging member ban: {e}")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Log role changes."""
    if before.roles == after.roles:
        return
    
    # Check what changed
    added_roles = [r for r in after.roles if r not in before.roles]
    removed_roles = [r for r in before.roles if r not in after.roles]
    
    if not added_roles and not removed_roles:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='role_change' AND enabled=1
        """, (after.guild.id,))
        row = await cur.fetchone()
    
    if row:
        log_channel = after.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                desc = f"**User:** {after.mention} ({after})\n"
                if added_roles:
                    desc += f"**Added Roles:** {', '.join([r.mention for r in added_roles if r != after.guild.default_role])}\n"
                if removed_roles:
                    desc += f"**Removed Roles:** {', '.join([r.mention for r in removed_roles if r != after.guild.default_role])}\n"
                
                embed = obsidian_embed(
                    "🎭 Role Updated",
                    desc,
                    color=discord.Color.blue(),
                    client=bot,
                )
                await log_channel.send(embed=embed)
            except Exception as e:
                logger.error(f"[logging] Error logging role change: {e}")


async def main():
    # Initialize database and verify persistence
    await init_db()
    
    # Verify database file exists and is accessible
    import os
    db_dir = os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "."
    db_filename = os.path.basename(DB_PATH)
    
    # Log database location info
    logger.info(f"[startup] Database path: {DB_PATH}")
    logger.info(f"[startup] Database directory: {os.path.abspath(db_dir)}")
    logger.info(f"[startup] Database filename: {db_filename}")
    
    if os.path.exists(DB_PATH):
        db_size = os.path.getsize(DB_PATH)
        logger.info(f"[startup] Database file found: {DB_PATH} ({db_size} bytes)")
        
        # Check if directory is writable
        if os.access(db_dir, os.W_OK):
            logger.info(f"[startup] Database directory is writable: {db_dir}")
        else:
            logger.warning(f"[startup] Database directory may not be writable: {db_dir}")
    else:
        logger.warning(f"[startup] Database file not found: {DB_PATH} (will be created)")
        
        # Check if directory exists and is writable
        if not os.path.exists(db_dir):
            logger.warning(f"[startup] Database directory does not exist: {db_dir} (will be created)")
        elif not os.access(db_dir, os.W_OK):
            logger.error(f"[startup] Database directory is not writable: {db_dir}")
        else:
            logger.info(f"[startup] Database directory is writable: {db_dir}")
    
    # Verify update log tables exist
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if update_log_settings table exists
        cur = await db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='update_log_settings'
        """)
        if not await cur.fetchone():
            logger.error("[startup] CRITICAL: update_log_settings table not found!")
        else:
            logger.info("[startup] Update log settings table verified")
        
        # Check if bot_version_tracking table exists
        cur = await db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='bot_version_tracking'
        """)
        if not await cur.fetchone():
            logger.error("[startup] CRITICAL: bot_version_tracking table not found!")
        else:
            logger.info("[startup] Bot version tracking table verified")
    
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
        print("  - Message Content Intent (PRIVILEGED)")
        print("\nTo enable:")
        print("1. Go to: https://discord.com/developers/applications/")
        print("2. Select your application")
        print("3. Go to the 'Bot' section")
        print("4. Enable 'SERVER MEMBERS INTENT' under Privileged Gateway Intents")
        print("5. Enable 'MESSAGE CONTENT INTENT' under Privileged Gateway Intents")
        print("6. Save changes and restart the bot\n")
        print("="*60 + "\n")
        raise
    except KeyboardInterrupt:
        print("\n[shutdown] Bot stopped by user")
    except Exception as e:
        print(f"\n[error] Bot crashed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
