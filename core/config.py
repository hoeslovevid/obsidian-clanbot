"""
Central configuration for Obsidian Clan Bot.
All environment variables and config values are loaded here to keep bot/app.py lean
and avoid loading heavy modules at startup.
"""
import os
from pathlib import Path

from dotenv import load_dotenv  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    for env_path in (PROJECT_ROOT / "config" / ".env", PROJECT_ROOT / ".env"):
        if env_path.is_file():
            load_dotenv(env_path)
            return
    load_dotenv()


_load_env()

# --- Required ---
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError(
        "Missing DISCORD_TOKEN environment variable. "
        "Please set DISCORD_TOKEN in your environment variables or Railway dashboard."
    )

# --- Optional (dev fast-sync to one guild; production multi-guild uses global sync) ---
GUILD_ID = int(os.getenv("GUILD_ID", "0") or "0")
# When true AND GUILD_ID is set, sync only to that guild (local dev). Default false for 78+ guilds.
COMMAND_SYNC_GUILD_ONLY = os.getenv("COMMAND_SYNC_GUILD_ONLY", "false").lower() in (
    "1", "true", "yes", "y", "on",
)

# --- Moderation ---
# Optional: role name(s) for temp VC staff access (comma-separated in MOD_ROLE_NAMES)
MOD_ROLE_NAME = os.getenv("MOD_ROLE_NAME", "").strip() or None
MOD_ROLE_NAMES = [
    n.strip()
    for n in os.getenv("MOD_ROLE_NAMES", "").split(",")
    if n.strip()
]

# --- Bot branding (optional) ---
BOT_STATUS = os.getenv("BOT_STATUS", "Discord")  # Custom status text (e.g. "Watching Discord")
BOT_WEBSITE = (os.getenv("BOT_WEBSITE", "https://obsidianoverseer.com").strip() or None)  # /about, /links, presence
BOT_DEVELOPER = os.getenv("BOT_DEVELOPER", "Danger!")  # Developer name/credit (e.g. "YourName#1234")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

# --- Database ---
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "obsidian_clanbot.db"))
# sqlite (default) | postgres (2.1 preview — requires DATABASE_URL + asyncpg)
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or None

# --- Version ---
# Single source of truth for /about, /whatsnew, /status, release announce, and slash-command sync.
# Set BOT_VERSION on Railway to match each production release; keep this code default in sync.
# On release: bump BOT_VERSION here (and on Railway), then update CURRENT_RELEASE_* in core/changelog.py.
BOT_VERSION = os.getenv("BOT_VERSION", "2.3.4")
BOT_CHANGELOG = os.getenv(
    "BOT_CHANGELOG",
    "v2.3.4 — Website nav fix, dashboard page, contact via bot API; see /whatsnew.",
)

# Presence rotation: default | menu | degraded | event
PRESENCE_MODE = os.getenv("PRESENCE_MODE", "default")

# --- Temp VC ---
TEMP_VC_CATEGORY_ID = int(os.getenv("TEMP_VC_CATEGORY_ID", "0") or "0")
TEMP_VC_CATEGORY_NAME = os.getenv("TEMP_VC_CATEGORY_NAME", "Temp VCs")
CREATE_VC_NAME = os.getenv("CREATE_VC_NAME", "➕ Form Squad")
VOICE_IDLE_DELETE_MINUTES = int(os.getenv("VOICE_IDLE_DELETE_MINUTES", "5"))
VC_CLEANUP_INTERVAL_MINUTES = int(os.getenv("VC_CLEANUP_INTERVAL_MINUTES", "2"))
VC_PANEL_UPDATE_DEBOUNCE_SECONDS = float(os.getenv("VC_PANEL_UPDATE_DEBOUNCE_SECONDS", "8"))

# --- Channels ---
VOICE_PANEL_CHANNEL_ID = int(os.getenv("VOICE_PANEL_CHANNEL_ID", "0") or "0")
VOICE_PANEL_CHANNEL_NAME = os.getenv("VOICE_PANEL_CHANNEL_NAME", "obsidian-console")
COMPLAINTS_CHANNEL_ID = int(os.getenv("COMPLAINTS_CHANNEL_ID", "0") or "0")
COMPLAINTS_CHANNEL_NAME = os.getenv("COMPLAINTS_CHANNEL_NAME", "inheritor-docket")
COMPLAINTS_LOG_CHANNEL_ID = int(os.getenv("COMPLAINTS_LOG_CHANNEL_ID", "0") or "0")
COMPLAINTS_LOG_CHANNEL_NAME = os.getenv("COMPLAINTS_LOG_CHANNEL_NAME", "docket-ledger")
EVENTS_CHANNEL_ID = int(os.getenv("EVENTS_CHANNEL_ID", "0") or "0")
EVENTS_CHANNEL_NAME = os.getenv("EVENTS_CHANNEL_NAME", "ops-board")

# --- Economy ---
ECONOMY_ENABLED = os.getenv("ECONOMY_ENABLED", "true").lower() == "true"
COINS_PER_MESSAGE = int(os.getenv("COINS_PER_MESSAGE", "10"))
COINS_PER_MINUTE_VOICE = int(os.getenv("COINS_PER_MINUTE_VOICE", "4"))
COINS_DAILY_REWARD = int(os.getenv("COINS_DAILY_REWARD", "200"))
MESSAGE_COOLDOWN_SECONDS = int(os.getenv("MESSAGE_COOLDOWN_SECONDS", "60"))
VOICE_REWARD_INTERVAL_MINUTES = int(os.getenv("VOICE_REWARD_INTERVAL_MINUTES", "1"))
MIN_VOICE_MINUTES_FOR_REWARD = int(os.getenv("MIN_VOICE_MINUTES_FOR_REWARD", "1"))

# --- Events ---
EVENT_REMINDER_MINUTES_BEFORE = int(os.getenv("EVENT_REMINDER_MINUTES_BEFORE", "60"))
EVENT_REMINDER_LOOP_MINUTES = int(os.getenv("EVENT_REMINDER_LOOP_MINUTES", "1"))

# --- Auto setup ---
# Default false: do not auto-create channels without permission. Run /setup_obsidian to configure.
AUTO_SETUP = os.getenv("AUTO_SETUP", "false").lower() in ("1", "true", "yes", "y", "on")

# When true, new guild joins disable music/pets/gambling until mods opt in (/admin features).
DEFAULT_LEAN_FEATURES = os.getenv("DEFAULT_LEAN_FEATURES", "true").lower() in (
    "1", "true", "yes", "y", "on",
)

# --- Mention chat (hybrid: keywords + optional AI) ---
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip() or None

# --- Embed / UX ---
HELP_LAYOUT_V2 = os.getenv("HELP_LAYOUT_V2", "true").lower() in ("1", "true", "yes", "y", "on")
# Live open-world cycles panel refresh interval (minutes, default 5; clamped 3–15 in tasks).
CYCLE_LIVE_UPDATE_MINUTES = os.getenv("CYCLE_LIVE_UPDATE_MINUTES", "5")
# Optional full URL for embed banner image (showcase, errors, level-ups). When unset,
# defaults to GitHub raw assets/obsidian_embed_banner.png under GITHUB_RAW_REPO.
EMBED_BANNER_URL = os.getenv("EMBED_BANNER_URL", "").strip() or None
EMBED_LOGO_URL = os.getenv("EMBED_LOGO_URL", "").strip() or None
GITHUB_RAW_REPO = os.getenv("GITHUB_RAW_REPO", "hoeslovevid/obsidian-clanbot").strip()

# --- Web dashboard API (optional HTTP server for external site integration) ---
DASHBOARD_API_ENABLED = os.getenv("DASHBOARD_API_ENABLED", "false").lower() in (
    "1", "true", "yes", "y", "on",
)
# Railway sets PORT; fall back to DASHBOARD_API_PORT for local dev.
DASHBOARD_API_PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_API_PORT", "8080")) or "8080")
# Shared secret for your website backend (never expose to the browser).
DASHBOARD_API_SECRET = (os.getenv("DASHBOARD_API_SECRET") or "").strip() or None
# Comma-separated origins for CORS (defaults to BOT_WEBSITE when set).
_cors_raw = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
if _cors_raw:
    DASHBOARD_CORS_ORIGINS: tuple[str, ...] = tuple(
        o.strip() for o in _cors_raw.split(",") if o.strip()
    )
elif BOT_WEBSITE:
    DASHBOARD_CORS_ORIGINS = (BOT_WEBSITE.rstrip("/"),)
else:
    DASHBOARD_CORS_ORIGINS = ()
# Discord OAuth app client id (same app as the bot) — used in /api/auth docs only.
DISCORD_CLIENT_ID = (os.getenv("DISCORD_CLIENT_ID") or "").strip() or None
# Contact form → Discord channel (server-side only; used by POST /api/contact).
CONTACT_WEBHOOK_URL = (os.getenv("CONTACT_WEBHOOK_URL") or "").strip() or None
