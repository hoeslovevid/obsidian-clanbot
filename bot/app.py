import os
import re
import time
import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, Union

import aiosqlite  # type: ignore
import aiohttp  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore
from discord import app_commands  # type: ignore
from discord.ext import commands, tasks  # type: ignore
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
# - Ops events (natural language time parsing, RSVP, reminder)
# ============================================================

# Import config first (loads env, no heavy deps)
from core.db import open_db, is_db_locked_error
from core.config import (
    TOKEN, GUILD_ID, MOD_ROLE_NAME, BOT_STATUS, TIMEZONE, DB_PATH,
    BOT_VERSION, BOT_CHANGELOG,
    TEMP_VC_CATEGORY_ID, TEMP_VC_CATEGORY_NAME, CREATE_VC_NAME,
    VOICE_IDLE_DELETE_MINUTES, VC_CLEANUP_INTERVAL_MINUTES, VC_PANEL_UPDATE_DEBOUNCE_SECONDS,
    VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME,
    COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME,
    COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME,
    EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME,
    ECONOMY_ENABLED, COINS_PER_MESSAGE, COINS_PER_MINUTE_VOICE,
    COINS_DAILY_REWARD, MESSAGE_COOLDOWN_SECONDS,
    VOICE_REWARD_INTERVAL_MINUTES, MIN_VOICE_MINUTES_FOR_REWARD,
    EVENT_REMINDER_MINUTES_BEFORE, EVENT_REMINDER_LOOP_MINUTES,
    AUTO_SETUP, OPENAI_API_KEY,
)

# Re-export config for modules that import from bot (backward compat)
__all__ = [
    "bot", "check_auto_mod", "post_vc_panel", "update_vc_panel_embed", "log_complaint_action",
    "TOKEN", "GUILD_ID", "MOD_ROLE_NAME", "BOT_STATUS", "TIMEZONE", "DB_PATH",
    "BOT_VERSION", "BOT_CHANGELOG",
    "TEMP_VC_CATEGORY_ID", "TEMP_VC_CATEGORY_NAME", "CREATE_VC_NAME",
    "VOICE_PANEL_CHANNEL_ID", "VOICE_PANEL_CHANNEL_NAME",
    "COMPLAINTS_CHANNEL_ID", "COMPLAINTS_CHANNEL_NAME",
    "COMPLAINTS_LOG_CHANNEL_ID", "COMPLAINTS_LOG_CHANNEL_NAME",
    "EVENTS_CHANNEL_ID", "EVENTS_CHANNEL_NAME",
    "ECONOMY_ENABLED", "AUTO_SETUP",
    "ensure_core_channels", "resolve_channel_id", "ComplaintPanel",
    "ComplaintModView", "RSVPView", "add_coins", "get_user_balance",
    "transfer_coins", "get_user_xp", "detect_and_update_version",
]

# Intents
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.voice_states = True

# Import utilities and modules (avoid heavy: tasks, version_tracking, warframe_api)
from core.utils import obsidian_embed, extract_id, get_mod_role, is_mod, parse_time_natural, display_case_status
from database import (
    get_user_balance, add_coins, remove_coins, transfer_coins,
    get_user_xp, add_xp, calculate_level, xp_for_level, xp_for_next_level,
    get_guild_setting, set_guild_setting, now_utc, init_db
)
from core.channels import (
    resolve_channel_id, find_or_create_text_channel,
    resolve_temp_vc_category, ensure_join_to_create_channel, ensure_core_channels,
    delete_temp_vc_and_panel, delete_vc_panel_message
)
from core.modals import RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal, ComplaintModal, RequestInfoModal
from views import VCPanelView, ComplaintPanel, ComplaintModView, RSVPView, SetLimitView, SetLimitSelect
# tasks and version_tracking: lazy-import to defer ~2k lines until needed
def detect_and_update_version(*args, **kwargs):
    """Lazy wrapper - loads version_tracking only when called (e.g. /force_version_update)."""
    from core.version_tracking import detect_and_update_version as _fn
    return _fn(*args, **kwargs)




# Modal deduplication set now lives in handlers/modal_handler.py

# --------------------- Bot ---------------------
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.start_time = now_utc()

    async def setup_hook(self):
        from core.db import attach_bot_database

        attach_bot_database(self)

        # Sync commands only when BOT_VERSION changes (saves Discord API churn on restarts).
        from core.config import PROJECT_ROOT

        sync_marker = PROJECT_ROOT / "data" / ".command_sync_version"
        if sync_marker.is_file() and sync_marker.read_text(encoding="utf-8").strip() == BOT_VERSION:
            from core.command_tree_stats import collect_command_tree_stats

            self._command_tree_stats = collect_command_tree_stats(self)
            print(f"[sync] Skipping command sync — BOT_VERSION {BOT_VERSION} unchanged")
            return

        # Sync commands: to a single guild for speed if GUILD_ID set, else global.
        # Note: Commands are already loaded via load_all_commands() before bot creation
        try:
            if GUILD_ID:
                guild = discord.Object(id=GUILD_ID)
                # Don't use copy_global_to to avoid duplicates - just sync guild commands directly
                await self.tree.sync(guild=guild)
                self._last_command_sync = now_utc()
                self._command_sync_guild_id = GUILD_ID
                from core.command_tree_stats import collect_command_tree_stats

                self._command_tree_stats = collect_command_tree_stats(self)
                # List all registered commands for verification
                commands_list = [cmd.name for cmd in self.tree.get_commands(guild=None)]
                print(f"[sync] Synced {len(commands_list)} top-level commands/groups to guild {GUILD_ID}")
                print(f"[sync] Top-level: {', '.join(commands_list)}")
                
                # Verify groups and their subcommands
                total_subcommands = 0
                for cmd in self.tree.get_commands(guild=None):
                    if isinstance(cmd, app_commands.Group):
                        subcommands = [subcmd.name for subcmd in cmd.commands]
                        total_subcommands += len(subcommands)
                        if len(subcommands) > 0:
                            print(f"[sync] Group '{cmd.name}' has {len(subcommands)} subcommands: {', '.join(sorted(subcommands[:10]))}{'...' if len(subcommands) > 10 else ''}")
                        else:
                            print(f"[sync] WARNING: Group '{cmd.name}' has NO subcommands!")
                print(f"[sync] Total subcommands synced: {total_subcommands}")
            else:
                await self.tree.sync()
                self._last_command_sync = now_utc()
                self._command_sync_guild_id = None
                from core.command_tree_stats import collect_command_tree_stats

                self._command_tree_stats = collect_command_tree_stats(self)
                commands_list = [cmd.name for cmd in self.tree.get_commands(guild=None)]
                print(f"[sync] Synced {len(commands_list)} top-level commands/groups globally (may take a while to appear)")
                print(f"[sync] Top-level: {', '.join(commands_list)}")
                
                # Verify groups and their subcommands
                total_subcommands = 0
                for cmd in self.tree.get_commands(guild=None):
                    if isinstance(cmd, app_commands.Group):
                        subcommands = [subcmd.name for subcmd in cmd.commands]
                        total_subcommands += len(subcommands)
                        if len(subcommands) > 0:
                            print(f"[sync] Group '{cmd.name}' has {len(subcommands)} subcommands: {', '.join(sorted(subcommands[:10]))}{'...' if len(subcommands) > 10 else ''}")
                        else:
                            print(f"[sync] WARNING: Group '{cmd.name}' has NO subcommands!")
                print(f"[sync] Total subcommands synced: {total_subcommands}")
            try:
                sync_marker.parent.mkdir(parents=True, exist_ok=True)
                sync_marker.write_text(BOT_VERSION, encoding="utf-8")
            except Exception as sync_err:
                logger.debug("[sync] Could not write sync version marker: %s", sync_err)
        except discord.app_commands.errors.CommandSyncFailure as e:
            print(f"[sync] Failed to sync commands: {e}")
            # discord.py CommandSyncFailure attributes vary by version; use getattr for type checkers
            err: Any = e
            errs = getattr(err, "errors", None)
            if errs:
                print(f"[sync] Error details: {errs}")
            cmd_list = getattr(err, "commands", None) or []
            print(f"[sync] Commands being synced: {len(cmd_list)}")
            for cmd in cmd_list:
                if isinstance(cmd, app_commands.Command):
                    for param in getattr(cmd, "parameters", []):
                        if getattr(param, "choices", None):
                            for choice in param.choices:
                                if len(choice.name) >= 25:
                                    print(f"[sync] ERROR: Command '{cmd.name}' has choice '{choice.name}' with {len(choice.name)} characters!")
                elif isinstance(cmd, app_commands.Group):
                    for subcmd in cmd.commands:
                        for param in getattr(subcmd, "parameters", []):
                            if getattr(param, "choices", None):
                                for choice in param.choices:
                                    if len(choice.name) >= 25:
                                        print(f"[sync] ERROR: Group '{cmd.name}' subcommand '{subcmd.name}' has choice '{choice.name}' with {len(choice.name)} characters!")
            import traceback
            traceback.print_exc()
        except Exception as e:
            print(f"[sync] Failed to sync commands: {e}")
            import traceback
            traceback.print_exc()


bot = ClanBot()

# Load commands from commands_loader (cleaner, easier to debug)
from core.commands_loader import load_all_commands
load_all_commands(bot)

# --------------------- Global app command checks ---------------------
# Slash command start times (interaction uses __slots__; cannot set arbitrary attrs).
_cmd_start_times: dict[int, float] = {}

# Incident mode: block non-critical commands for non-mods.
async def incident_mode_check(interaction: discord.Interaction) -> bool:
    iid = getattr(interaction, "id", None)
    if iid is not None:
        _cmd_start_times[int(iid)] = time.perf_counter()
    try:
        if not interaction.guild:
            return True

        # Mods are always allowed
        if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
            return True

        from database import get_guild_setting, set_guild_setting

        enabled = await get_guild_setting(interaction.guild.id, "incident_mode_enabled")
        if (enabled or "0") != "1":
            return True

        # Auto-disable if expired
        until_s = await get_guild_setting(interaction.guild.id, "incident_mode_until_ts")
        until_ts = int(until_s) if until_s and until_s.isdigit() else 0
        now_ts = int(now_utc().timestamp())
        if until_ts and now_ts > until_ts:
            await set_guild_setting(interaction.guild.id, "incident_mode_enabled", "0")
            await set_guild_setting(interaction.guild.id, "incident_mode_until_ts", "0")
            return True

        # Allow-list: keep support + help available
        qualified = ""
        try:
            qualified = interaction.command.qualified_name if interaction.command else ""
        except Exception:
            qualified = ""

        allowed = {
            # Moderation
            "mod",
            "mod logging",
            "mod incident",
            "mod kpis",
            # Support / events
            "community ticket",
            "community ticket_close",
            "community event_create",
            # Help / status
            "general help",
            "general bot_status",
            "status",
        }

        # Any command under /mod is allowed
        if qualified == "mod" or qualified.startswith("mod "):
            return True

        if qualified in allowed:
            return True

        msg = await get_guild_setting(interaction.guild.id, "incident_mode_message")
        reason = msg.strip() if msg else (
            "The server is in **incident mode** while staff handle an issue. "
            "Most commands are paused for now — you can still use **`/help`**, **`/status`**, or **`/ticket`**."
        )
        until_line = ""
        if until_ts and until_ts > now_ts:
            until_line = f"\n\n_Auto-resumes <t:{until_ts}:R> (<t:{until_ts}:F>)._"
        if not interaction.response.is_done():
            from core.embed_templates import embed_template
            await interaction.response.send_message(
                embed=embed_template(
                    "warning",
                    "🚨 Incident Mode",
                    f"{reason}{until_line}",
                    category="moderation",
                    client=bot,
                ),
                ephemeral=True,
            )
        return False
    except Exception:
        # Fail open (never break commands)
        return True

def _install_incident_mode_interaction_check():
    """
    discord.py 2.6.x does not have CommandTree.check.
    Use CommandTree.interaction_check to apply a global gate.
    """
    prev = getattr(bot.tree, "interaction_check", None)

    async def combined(interaction: discord.Interaction) -> bool:
        # Preserve any previous interaction_check behavior (if customized)
        try:
            if prev:
                res = prev(interaction)
                if hasattr(res, "__await__"):
                    res = await res
                if res is False:
                    return False
        except Exception:
            # If previous check fails, fail open
            pass

        return await incident_mode_check(interaction)

    try:
        bot.tree.interaction_check = combined  # type: ignore[attr-defined]
    except Exception:
        # If we can't install for any reason, fail open
        pass


_install_incident_mode_interaction_check()


# Database initialization is now in database.py


def _channel_mention_safe(channel: Any) -> str:
    """Discord.py stubs omit .mention on some channel types; runtime has it on guild text-like channels."""
    if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
        return channel.mention
    cid = getattr(channel, "id", 0)
    return f"<#{cid}>"


def _channel_name_safe(channel: Any) -> str:
    """Channel name for logging; works when .name is missing on stubs."""
    n = getattr(channel, "name", None)
    return n if isinstance(n, str) else "channel"


def format_thread_name(
    case_id: str,
    user: Union[discord.User, discord.Member],
    category: str = "",
    date_str: Optional[str] = None,
) -> str:
    """
    Format a thread name for complaint threads.
    Format: "{username} • {date} • {case_id}"
    Discord thread names max at 100 characters.
    """
    # Get username (display_name or name, max 30 chars)
    username = (getattr(user, "display_name", None) or user.name)
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
    async with open_db() as db:
        await db.execute(
            "INSERT INTO complaint_actions(guild_id,case_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?,?)",
            (guild.id, case_id, actor_id, action, note, now_utc().isoformat()),
        )
        await db.commit()

    # Optional ledger channel
    ledger_id = await resolve_channel_id(guild, "complaints_log_channel_id", COMPLAINTS_LOG_CHANNEL_ID, COMPLAINTS_LOG_CHANNEL_NAME)
    if ledger_id:
        ch = guild.get_channel(ledger_id)
        if isinstance(ch, discord.TextChannel):
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

    everyone_ow = vc.overwrites_for(guild.default_role)
    locked = everyone_ow.connect is False
    members = len(vc.members)
    cap = vc.user_limit if vc.user_limit else "∞"
    lock_label = "🔒 Sealed" if locked else "🔓 Open"

    embed = obsidian_embed(
        "Voice Channel Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner.mention}\n"
        f"**Members:** {members}/{cap}\n"
        f"**Status:** {lock_label}\n\n"
        "Configure your voice channel using the controls below.\n"
        "_Squad owners and configured staff roles can use these controls._",
        color=discord.Color.dark_grey(),
        client=bot,
    )
    view = VCPanelView(vc.id)
    msg = await panel_ch.send(embed=embed, view=view)

    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO vc_panels(guild_id, channel_id, message_id) VALUES(?,?,?)",
            (guild.id, vc.id, msg.id),
        )
        await db.commit()

    # Register persistent view (so buttons keep working after restart)
    bot.add_view(view)


_vc_panel_fingerprint: Dict[Tuple[int, int], str] = {}
_guild_pending_vc_updates: Dict[int, set[int]] = {}
_guild_vc_flush_tasks: Dict[int, asyncio.Task] = {}


async def update_vc_panel_embed(guild: discord.Guild, vc_id: int, *, force: bool = False) -> None:
    """Edit the VC panel message with live member count and lock status."""
    async with open_db() as db:
        cur = await db.execute(
            "SELECT message_id FROM vc_panels WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        row = await cur.fetchone()
    if not row:
        return

    vc = guild.get_channel(vc_id)
    if not isinstance(vc, discord.VoiceChannel):
        return

    panel_ch_id = await resolve_channel_id(
        guild, "voice_panel_channel_id", VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
    )
    panel_ch = guild.get_channel(panel_ch_id) if panel_ch_id else None
    if not isinstance(panel_ch, discord.TextChannel):
        return

    async with open_db() as db:
        cur = await db.execute(
            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
            (guild.id, vc_id),
        )
        owner_row = await cur.fetchone()
    owner_id = int(owner_row[0]) if owner_row else 0
    owner = guild.get_member(owner_id)
    owner_line = owner.mention if owner else f"<@{owner_id}>" if owner_id else "—"

    everyone_ow = vc.overwrites_for(guild.default_role)
    locked = everyone_ow.connect is False
    members = len(vc.members)
    cap = vc.user_limit if vc.user_limit else "∞"
    lock_label = "🔒 Sealed" if locked else "🔓 Open"

    fingerprint = f"{members}|{cap}|{locked}|{owner_id}"
    fp_key = (guild.id, vc_id)
    if not force and _vc_panel_fingerprint.get(fp_key) == fingerprint:
        return

    embed = obsidian_embed(
        "Voice Channel Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner_line}\n"
        f"**Members:** {members}/{cap}\n"
        f"**Status:** {lock_label}\n\n"
        "Configure your voice channel using the controls below.\n"
        "_Squad owners and configured staff roles can use these controls._",
        color=discord.Color.dark_grey(),
        client=bot,
    )

    try:
        from core.safe_message_edit import safe_message_edit

        msg = await panel_ch.fetch_message(int(row[0]))
        await safe_message_edit(msg, embed=embed, view=VCPanelView(vc_id))
        _vc_panel_fingerprint[fp_key] = fingerprint
    except Exception:
        pass


async def schedule_vc_panel_embed_update(guild: discord.Guild, vc_id: int) -> None:
    """Coalesce voice-triggered VC panel refreshes per guild (avoids channel edit bursts)."""
    gid = guild.id
    _guild_pending_vc_updates.setdefault(gid, set()).add(vc_id)

    existing = _guild_vc_flush_tasks.get(gid)
    if existing and not existing.done():
        return

    async def _flush_guild_panels() -> None:
        try:
            await asyncio.sleep(VC_PANEL_UPDATE_DEBOUNCE_SECONDS)
            vc_ids = _guild_pending_vc_updates.pop(gid, set())
            from core.safe_message_edit import CHANNEL_EDIT_MIN_INTERVAL

            for index, vid in enumerate(sorted(vc_ids)):
                if index > 0:
                    await asyncio.sleep(CHANNEL_EDIT_MIN_INTERVAL)
                await update_vc_panel_embed(guild, vid)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            _guild_vc_flush_tasks.pop(gid, None)

    _guild_vc_flush_tasks[gid] = asyncio.create_task(_flush_guild_panels())


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
    from core.utils import is_mod
    
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
                        f"**Channel:** {_channel_mention_safe(message.channel)}\n"
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

    # Bot mention: hybrid response (keywords + optional AI)
    if message.guild.me in message.mentions:
        try:
            from core.mention_chat import get_mention_reply
            reply = await get_mention_reply(
                message.content,
                message.guild.me.id,
                OPENAI_API_KEY,
                bot=bot,
            )
            from core.embed_footers import footer_for
            from core.embed_templates import embed_template
            embed = embed_template(
                "showcase",
                "💬 Obsidian Bot",
                reply,
                category="general",
                footer=footer_for("mention"),
                client=bot,
            )
            await message.reply(embed=embed, mention_author=False)
            return  # Don't process economy for mention-only messages
        except discord.Forbidden:
            pass

    # Ticket enhancements: track ticket SLA / activity timestamps
    # Only do DB work if message is inside the Tickets category
    try:
        if isinstance(message.channel, discord.TextChannel) and message.channel.category and message.channel.category.name == "Tickets":
            now_iso = now_utc().isoformat()
            is_staff = isinstance(message.author, discord.Member) and is_mod(message.author)
            async with open_db() as db:
                cur = await db.execute(
                    "SELECT user_id FROM tickets WHERE guild_id=? AND channel_id=? AND status!='closed'",
                    (message.guild.id, message.channel.id),
                )
                owner_row = await cur.fetchone()
                new_status = None
                if owner_row:
                    owner_id = int(owner_row[0])
                    if is_staff:
                        new_status = "awaiting_member"
                    elif message.author.id == owner_id:
                        new_status = "awaiting_staff"
                await db.execute(
                    """
                    UPDATE tickets
                    SET last_activity_at=?,
                        status=COALESCE(?, status),
                        first_response_at=CASE
                            WHEN ?=1 AND (first_response_at IS NULL OR first_response_at='') THEN ?
                            ELSE first_response_at
                        END
                    WHERE guild_id=? AND channel_id=? AND status!='closed'
                    """,
                    (
                        now_iso,
                        new_status,
                        1 if is_staff else 0,
                        now_iso,
                        message.guild.id,
                        message.channel.id,
                    ),
                )
                await db.commit()
            if new_status:
                from commands.tickets.ticket import sync_ticket_status_for_channel

                await sync_ticket_status_for_channel(message.guild, message.channel.id, new_status)
    except Exception:
        # Never break message handling because of ticket tracking
        pass
    
    # Check auto-moderation first (this may delete the message)
    violation_handled = await check_auto_mod(message)
    if violation_handled:
        return  # Message was deleted/punished, don't process economy

    # Passive typo helper: catches !command / /command / .command attempts and
    # suggests the closest registered slash command. Cheap pre-filter, falls
    # through to economy/XP if nothing matches.
    try:
        from core.typo_helper import maybe_suggest_command
        await maybe_suggest_command(message, bot)
    except Exception as _typo_err:
        logger.debug(f"[typo_helper] error: {_typo_err}")

    # Check if economy is enabled
    if not ECONOMY_ENABLED:
        return

    # Item 85 — per-guild kill switch overrides global flag.
    try:
        from core.utils import feature_enabled
        if not await feature_enabled(message.guild.id, "economy_passive"):
            return
    except Exception:
        pass

    # Ignore commands (they're handled separately)
    if message.content.startswith("!"):
        return

    try:
        await _award_message_economy(message)
    except Exception as econ_err:
        if is_db_locked_error(econ_err):
            logger.warning(
                "Message economy skipped (database locked): guild=%s user=%s",
                message.guild.id,
                message.author.id,
            )
            return
        logger.error("Message economy error: %s", econ_err, exc_info=True)
        return

    # Item 83 — proactively clear the inactive role when a tagged member returns.
    if isinstance(message.author, discord.Member):
        try:
            from commands.moderation.inactive_role import maybe_clear_inactive_role
            await maybe_clear_inactive_role(message.author)
        except Exception:
            pass

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
    guild = member.guild
    # Economy voice tracking (if enabled) — single connection per event when possible
    if ECONOMY_ENABLED:
        now = now_utc()
        ch_before = before.channel if isinstance(before.channel, discord.VoiceChannel) else None
        ch_after = after.channel if isinstance(after.channel, discord.VoiceChannel) else None
        needs_voice_db = bool(ch_before) or (
            ch_after is not None and not (after.self_mute or after.self_deaf)
        )
        if needs_voice_db:
            async with open_db() as db:
                if ch_before:
                    await db.execute(
                        "DELETE FROM voice_activity WHERE guild_id=? AND user_id=? AND channel_id=?",
                        (guild.id, member.id, ch_before.id),
                    )
                if ch_after is not None and not (after.self_mute or after.self_deaf):
                    cur = await db.execute(
                        """
                        SELECT total_minutes FROM voice_activity
                        WHERE guild_id=? AND user_id=? AND channel_id=?
                        """,
                        (guild.id, member.id, ch_after.id),
                    )
                    row = await cur.fetchone()
                    existing_minutes = row[0] if row else 0
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO voice_activity
                        (guild_id, user_id, channel_id, joined_at, last_reward_at, total_minutes)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (guild.id, member.id, ch_after.id, now.isoformat(), None, existing_minutes),
                    )
                await db.commit()
        if ch_after is not None:
            try:
                from commands.moderation.inactive_role import maybe_clear_inactive_role
                await maybe_clear_inactive_role(member)
            except Exception:
                pass
    
    # Original join-to-create logic
    guild = member.guild

    async def _maybe_refresh_vc_panel(
        channel: Optional[discord.VoiceChannel],
        *,
        db: Optional[aiosqlite.Connection] = None,
    ) -> None:
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            return

        async def _is_temp_vc(conn: aiosqlite.Connection) -> bool:
            cur = await conn.execute(
                "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (guild.id, channel.id),
            )
            return await cur.fetchone() is not None

        try:
            if db is not None:
                if await _is_temp_vc(db):
                    await schedule_vc_panel_embed_update(guild, channel.id)
                return
            async with open_db() as conn:
                if await _is_temp_vc(conn):
                    await schedule_vc_panel_embed_update(guild, channel.id)
        except Exception:
            pass

    ch_before_vc = before.channel if isinstance(before.channel, discord.VoiceChannel) else None
    ch_after_vc = after.channel if isinstance(after.channel, discord.VoiceChannel) else None
    panel_channels = [c for c in (ch_before_vc, ch_after_vc) if c is not None]
    if panel_channels:
        async with open_db() as vc_db:
            for ch in panel_channels:
                await _maybe_refresh_vc_panel(ch, db=vc_db)

    if not after.channel:
        return

    create_id_s = await get_guild_setting(member.guild.id, "create_vc_channel_id")
    if not (create_id_s and create_id_s.isdigit()):
        return

    create_id = int(create_id_s)
    if after.channel.id != create_id:
        # Track last non-empty times for cleanup
        nonempty_channels = [
            ch
            for ch in (before.channel, after.channel)
            if ch and isinstance(ch, discord.VoiceChannel) and len(ch.members) > 0
        ]
        if nonempty_channels:
            now_iso = now_utc().isoformat()
            async with open_db() as db:
                for ch in nonempty_channels:
                    cur = await db.execute(
                        "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                        (guild.id, ch.id),
                    )
                    if await cur.fetchone():
                        await db.execute(
                            "UPDATE temp_vcs SET last_nonempty_at=? WHERE guild_id=? AND channel_id=?",
                            (now_iso, guild.id, ch.id),
                        )
                await db.commit()
        return
    category = await resolve_temp_vc_category(guild)
    create_ch = guild.get_channel(create_id)
    template_ch = create_ch if isinstance(create_ch, discord.VoiceChannel) else None
    from core.vc_permissions import build_temp_vc_overwrites, get_vc_staff_roles

    staff_roles = await get_vc_staff_roles(guild)

    # Create VC — seed hub/category overwrites, then owner + staff layers
    vc_name = f"{member.display_name} • Squad"
    overwrites = build_temp_vc_overwrites(
        guild,
        member,
        category=category,
        template_channel=template_ch,
        staff_roles=staff_roles,
    )

    new_vc = await guild.create_voice_channel(
        name=vc_name,
        category=category,
        overwrites=overwrites,
        reason="Join-to-create temp VC",
    )

    async with open_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) VALUES(?,?,?,?,?)",
            (guild.id, new_vc.id, member.id, now_utc().isoformat(), now_utc().isoformat()),
        )
        await db.commit()

    # Move member into new VC (they may disconnect while we create the channel).
    voice = member.voice
    if voice is None or voice.channel is None or voice.channel.id != create_id:
        logger.debug("[vc] %s left create channel before move; cleaning up %s", member.id, new_vc.id)
        try:
            await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (user left)")
        except Exception:
            pass
        return

    moved = False
    try:
        await member.move_to(new_vc, reason="Move to created squad VC")
        moved = True
    except discord.Forbidden:
        logger.debug("[vc] Missing Move Members permission for join-to-create")
    except discord.HTTPException as exc:
        if exc.code == 40032:  # Target user is not connected to voice
            logger.debug("[vc] move_to failed (not in voice) for %s; cleaning up %s", member.id, new_vc.id)
            try:
                await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (user disconnected)")
            except Exception:
                pass
            return
        logger.warning("[vc] move_to failed for %s: %s", member.id, exc)

    if not moved:
        if not new_vc.members:
            try:
                await delete_temp_vc_and_panel(guild, new_vc.id, reason="Join-to-create aborted (move failed)")
            except Exception:
                pass
        return

    # Post control panel
    try:
        await post_vc_panel(guild, new_vc, member)
    except Exception:
        pass


# --------------------- Component Router ---------------------
@bot.event
async def on_interaction(interaction: discord.Interaction):
    """
    Lightweight interaction router.
    Application commands are handled automatically by discord.py's command tree.
    Modal submissions → handlers/modal_handler.py
    Component interactions → handlers/component_handler.py
    """
    if interaction.type == discord.InteractionType.application_command:
        if isinstance(interaction.user, discord.Member) and interaction.guild:
            idata_cmd: Any = interaction.data or {}
            command_name = idata_cmd.get("name", "")
            if command_name not in ["activity", "activity_leaderboard"]:
                try:
                    from database import track_command_usage
                    await track_command_usage(interaction.guild.id, interaction.user.id)
                except Exception as e:
                    logger.debug(f"Failed to track command usage: {e}")
                try:
                    from core.command_history import qualified_command_name, record_recent_command

                    path = qualified_command_name(interaction)
                    if path:
                        await record_recent_command(interaction.guild.id, interaction.user.id, path)
                except Exception as e:
                    logger.debug(f"Failed to record recent command: {e}")
        return

    if interaction.type == discord.InteractionType.modal_submit:
        from handlers.modal_handler import handle_modal_submit
        await handle_modal_submit(bot, interaction)
        return

    if interaction.type == discord.InteractionType.component:
        from handlers.component_handler import handle_component
        await handle_component(bot, interaction)


# --------------------- Join-to-create logic ---------------------
# Background tasks are now in tasks.py and started via setup_tasks() in on_ready


# --------------------- Economy Commands ---------------------
# Economy commands are now loaded from commands/economy/ folder via load_all_commands()


# --------------------- Update Log Functions ---------------------
# Version tracking functions moved to version_tracking.py

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
    activity = _update_status_presence()
    await bot.change_presence(activity=activity, status=discord.Status.online)


@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Update status when bot leaves a guild."""
    activity = _update_status_presence()
    await bot.change_presence(activity=activity, status=discord.Status.online)


def _update_status_presence():
    """Update bot presence with website, /help hint, and guild count."""
    from core.presence import build_bot_activity
    return build_bot_activity(bot)


@bot.event
async def on_ready():
    """Bot ready event — delegates to handlers/startup.py for startup tasks."""
    from handlers.startup import run_startup
    await run_startup(bot)


# Cache for achievement definitions (avoid repeated initialization)
_achievement_definitions_initialized = False

# In-memory message economy cooldown — skip DB when still on cooldown
_MESSAGE_COOLDOWN_CACHE: Dict[Tuple[int, int], datetime] = {}


async def _award_message_economy(message: discord.Message) -> None:
    """Award passive coins/XP for a qualifying message (cooldown-gated)."""
    if not message.guild:
        return

    if _message_cooldown_active(message.guild.id, message.author.id):
        return

    async with open_db() as db:
        cur = await db.execute(
            "SELECT last_message_at FROM message_cooldowns WHERE guild_id=? AND user_id=?",
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()

        if row:
            last_message_at = datetime.fromisoformat(row[0])
            time_since = (now_utc() - last_message_at).total_seconds()
            if time_since < MESSAGE_COOLDOWN_SECONDS:
                _message_cooldown_touch(message.guild.id, message.author.id)
                return

        now_iso = now_utc().isoformat()
        await db.execute(
            """
            INSERT INTO message_cooldowns (guild_id, user_id, last_message_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET last_message_at=?
            """,
            (message.guild.id, message.author.id, now_iso, now_iso),
        )
        await db.commit()

    _message_cooldown_touch(message.guild.id, message.author.id)

    from core.utils import get_active_multiplier

    coins_mult = await get_active_multiplier(message.guild.id, "coins")
    await add_coins(
        message.guild.id,
        message.author.id,
        max(1, int(round(COINS_PER_MESSAGE * coins_mult))),
        "MESSAGE",
        f"Message in #{_channel_name_safe(message.channel)}",
    )

    from core.utils import XP_ENABLED, XP_PER_MESSAGE

    if not XP_ENABLED:
        return

    xp_mult = await get_active_multiplier(message.guild.id, "xp")
    leveled_up = await add_xp(
        message.guild.id,
        message.author.id,
        max(1, int(round(XP_PER_MESSAGE * xp_mult))),
        "MESSAGE",
    )
    if leveled_up and isinstance(message.author, discord.Member):
        xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
        logger.info(
            "User %s leveled up to level %s in guild %s",
            message.author.id,
            level,
            message.guild.id,
        )
        from core.utils import send_levelup_announcement

        await send_levelup_announcement(message.guild, message.author, level, xp, total_xp)

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
                    await message.author.add_roles(
                        *roles_to_add, reason=f"Leveled up to level {level}"
                    )
                    logger.info(
                        "Assigned level roles to %s: %s",
                        message.author.id,
                        [r.id for r in roles_to_add],
                    )
                except Exception as e:
                    logger.error("Error assigning level roles: %s", e)

    xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
    from database import check_and_record_milestone, check_and_unlock_achievement

    global _achievement_definitions_initialized
    if not _achievement_definitions_initialized:
        from database import (
            initialize_achievement_definitions,
            initialize_badge_definitions,
            initialize_title_definitions,
        )

        await initialize_achievement_definitions()
        await initialize_badge_definitions()
        await initialize_title_definitions()
        _achievement_definitions_initialized = True

    async with open_db() as db:
        cur = await db.execute(
            """
            SELECT messages_sent FROM activity_stats
            WHERE guild_id=? AND user_id=?
            """,
            (message.guild.id, message.author.id),
        )
        row = await cur.fetchone()
        message_count = row[0] if row else 0
        await db.execute(
            """
            INSERT INTO activity_stats (guild_id, user_id, messages_sent, last_activity_date)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                messages_sent = messages_sent + 1,
                last_activity_date = excluded.last_activity_date
            """,
            (message.guild.id, message.author.id, now_utc().isoformat()),
        )
        await db.commit()

    new_message_count = message_count + 1

    for milestone_level in (10, 25, 50, 100):
        if level >= milestone_level:
            milestone_achieved = await check_and_record_milestone(
                message.guild.id, message.author.id, "level", milestone_level
            )
            if milestone_achieved:
                await check_and_unlock_achievement(
                    message.guild.id,
                    message.author.id,
                    f"level_{milestone_level}",
                    bot,
                )

    achievement_map = {
        1: "first_message",
        100: "hundred_messages",
        1000: "thousand_messages",
        10000: "ten_thousand_messages",
    }
    for milestone_count in (1, 100, 1000, 10000):
        if new_message_count >= milestone_count:
            milestone_achieved = await check_and_record_milestone(
                message.guild.id, message.author.id, "message_count", milestone_count
            )
            if milestone_achieved and milestone_count in achievement_map:
                await check_and_unlock_achievement(
                    message.guild.id,
                    message.author.id,
                    achievement_map[milestone_count],
                    bot,
                )


def _message_cooldown_active(guild_id: int, user_id: int) -> bool:
    """True if user is still within MESSAGE_COOLDOWN_SECONDS (memory only)."""
    last = _MESSAGE_COOLDOWN_CACHE.get((guild_id, user_id))
    if last is None:
        return False
    return (now_utc() - last).total_seconds() < MESSAGE_COOLDOWN_SECONDS


def _message_cooldown_touch(guild_id: int, user_id: int) -> None:
    _MESSAGE_COOLDOWN_CACHE[(guild_id, user_id)] = now_utc()

@bot.event
async def on_member_join(member: discord.Member):
    """Send welcome message when a member joins."""
    # Check for join anniversary milestones (check existing join date)
    global _achievement_definitions_initialized
    from database import check_and_record_milestone, check_and_unlock_achievement, initialize_achievement_definitions, initialize_badge_definitions, initialize_title_definitions
    
    # Only initialize once (cached)
    if not _achievement_definitions_initialized:
        await initialize_achievement_definitions()
        await initialize_badge_definitions()
        await initialize_title_definitions()
        _achievement_definitions_initialized = True

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
    
    # Raid protection - record join
    try:
        from commands.moderation.raid_protection import record_join, check_raid_condition, trigger_raid_protection
        account_age = None
        if member.created_at:
            account_age = (now_utc() - member.created_at.replace(tzinfo=timezone.utc)).days
        await record_join(member.guild.id, member.id, account_age)
        
        # Check if raid conditions are met
        is_raid, join_count = await check_raid_condition(member.guild)
        if is_raid:
            await trigger_raid_protection(member.guild, join_count)
    except Exception as e:
        logger.error(f"[raid_protection] Error in raid protection: {e}")
    
    # Server milestones - check member count milestones
    try:
        from commands.general.milestones import check_and_celebrate_milestone
        member_count = member.guild.member_count
        # Check for round number milestones (100, 500, 1000, etc.)
        if member_count is not None and (
            member_count % 100 == 0
            or member_count in [50, 250, 500, 1000, 2500, 5000, 10000]
        ):
            await check_and_celebrate_milestone(member.guild, "member_count", member_count, bot=bot)
    except Exception as e:
        logger.error(f"[milestones] Error checking member count milestone: {e}")
    
    async with open_db() as db:
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

    # Optional: send welcome DM if configured
    try:
        dm_enabled = await get_guild_setting(member.guild.id, "welcome_dm_enabled")
        dm_msg = await get_guild_setting(member.guild.id, "welcome_dm_message")
        if dm_enabled == "1" and dm_msg:
            dm_text = dm_msg.replace("{user}", str(member)).replace("{server}", member.guild.name)
            dm_text = dm_text.replace("{member_count}", str(member.guild.member_count or 0))
            await member.send(dm_text[:2000])
    except (discord.Forbidden, discord.HTTPException):
        pass  # User may have DMs disabled

    # Default short welcome DM when no custom welcome_dm is configured.
    try:
        default_off = await get_guild_setting(member.guild.id, "welcome_dm_default_off")
        custom_dm = await get_guild_setting(member.guild.id, "welcome_dm_enabled")
        if default_off != "1" and custom_dm != "1":
            short = (
                f"Welcome to **{member.guild.name}**! "
                "Try `/menu` for quick actions, `/help` for commands, and `/preferences` to set your timezone."
            )
            await member.send(short[:2000])
    except (discord.Forbidden, discord.HTTPException):
        pass

    # Item 8: first-run onboarding DM (additive — runs alongside the welcome DM above).
    try:
        from commands.general.onboarding import maybe_send_onboarding_on_join
        await maybe_send_onboarding_on_join(member, bot)
    except Exception as e:
        logger.debug(f"[onboarding] join hook failed: {e}")
    
    # Format message
    formatted_message = message_template.replace("{user}", member.mention)
    formatted_message = formatted_message.replace("{server}", member.guild.name)
    formatted_message = formatted_message.replace("{member_count}", str(member.guild.member_count or 0))
    
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
                async with open_db() as db:
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
    async with open_db() as db:
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
    
    from core.leave_messages import format_leave_message

    formatted_message = format_leave_message(member, message_template)

    try:
        await channel.send(formatted_message)
    except Exception as e:
        logger.error(f"[leave] Error sending leave message: {e}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Handle reaction adds for starboard and other features."""
    # Starboard handling — read DB first, then do all network I/O with connection closed
    if payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
        if guild:
            # Phase 1: read-only DB fetch (connection opened and closed quickly)
            async with open_db() as db:
                cur = await db.execute(
                    "SELECT channel_id, threshold, emoji FROM starboard_settings WHERE guild_id=?",
                    (guild.id,),
                )
                sb_row = await cur.fetchone()

            if sb_row:
                starboard_channel_id, threshold, emoji = sb_row
                starboard_channel = guild.get_channel(starboard_channel_id)

                if isinstance(starboard_channel, discord.TextChannel) and str(payload.emoji) == emoji:
                    try:
                        channel = guild.get_channel(payload.channel_id)
                        if channel and isinstance(channel, discord.TextChannel):
                            # Network I/O — connection is already closed above
                            message = await channel.fetch_message(payload.message_id)
                            reaction = discord.utils.get(message.reactions, emoji=emoji)

                            if reaction and reaction.count >= threshold:
                                # Phase 2: check existing starboard entry (brief connection)
                                async with open_db() as db:
                                    cur = await db.execute("""
                                        SELECT starboard_message_id, stars FROM starboard_messages
                                        WHERE guild_id=? AND original_message_id=?
                                    """, (guild.id, message.id))
                                    existing = await cur.fetchone()

                                if existing:
                                    starboard_msg_id, old_stars = existing
                                    if reaction.count != old_stars:
                                        try:
                                            # Network I/O
                                            starboard_msg = await starboard_channel.fetch_message(starboard_msg_id)
                                            embed = starboard_msg.embeds[0] if starboard_msg.embeds else None
                                            if embed:
                                                embed.set_footer(text=f"{reaction.count} {emoji} | {_channel_mention_safe(message.channel)}")
                                                await starboard_msg.edit(embed=embed)
                                            # Phase 3: write (separate short connection)
                                            async with open_db() as db:
                                                await db.execute("""
                                                    UPDATE starboard_messages SET stars=?
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (reaction.count, guild.id, message.id))
                                                await db.commit()
                                        except discord.NotFound:
                                            async with open_db() as db:
                                                await db.execute("""
                                                    DELETE FROM starboard_messages
                                                    WHERE guild_id=? AND original_message_id=?
                                                """, (guild.id, message.id))
                                                await db.commit()
                                else:
                                    # Build and send new starboard embed (network I/O)
                                    embed = obsidian_embed(
                                        f"{emoji} {message.author.display_name}",
                                        message.content or "*No content*",
                                        color=discord.Color.gold(),
                                        client=bot,
                                    )
                                    embed.set_footer(text=f"{reaction.count} {emoji} | {_channel_mention_safe(message.channel)}")
                                    embed.timestamp = message.created_at
                                    if message.attachments:
                                        embed.set_image(url=message.attachments[0].url)
                                    starboard_msg = await starboard_channel.send(embed=embed)
                                    # Phase 3: write result
                                    async with open_db() as db:
                                        await db.execute("""
                                            INSERT INTO starboard_messages (guild_id, original_message_id, starboard_message_id, stars)
                                            VALUES (?, ?, ?, ?)
                                        """, (guild.id, message.id, starboard_msg.id, reaction.count))
                                        await db.commit()
                    except Exception as e:
                        logger.error(f"Error handling starboard reaction: {e}", exc_info=True)
    
    # Reaction role handling (guild DMs have no guild_id)
    gid_react = payload.guild_id
    if gid_react is None:
        return
    if payload.member and payload.member.bot:
        return

    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (gid_react, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(gid_react)
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
            
            # Send temporary confirmation message in channel (auto-deletes after 3 seconds)
            channel = guild.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    confirm_msg = await channel.send(
                        f"{member.mention} You have added {role.mention}!",
                        delete_after=3.0  # Delete after 3 seconds
                    )
                except discord.Forbidden:
                    # Can't send messages, that's okay
                    pass
                except Exception as e:
                    logger.debug(f"[reaction_role] Could not send confirmation message: {e}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to add role {role.name} to {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error adding role: {e}")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Handle reaction role removal."""
    gid_rm = payload.guild_id
    if gid_rm is None:
        return

    async with open_db() as db:
        cur = await db.execute("""
            SELECT role_id FROM reaction_roles
            WHERE guild_id = ? AND message_id = ? AND emoji = ?
        """, (gid_rm, payload.message_id, str(payload.emoji)))
        row = await cur.fetchone()
    
    if not row:
        return
    
    role_id = row[0]
    guild = bot.get_guild(gid_rm)
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
            
            # Send temporary confirmation message in channel (auto-deletes after 3 seconds)
            channel = guild.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    confirm_msg = await channel.send(
                        f"{member.mention} You have removed {role.mention}!",
                        delete_after=3.0  # Delete after 3 seconds
                    )
                except discord.Forbidden:
                    # Can't send messages, that's okay
                    pass
                except Exception as e:
                    logger.debug(f"[reaction_role] Could not send confirmation message: {e}")
    except discord.Forbidden:
        logger.warning(f"[reaction_role] No permission to remove role {role.name} from {member}")
    except Exception as e:
        logger.error(f"[reaction_role] Error removing role: {e}")


@bot.event
async def on_message_delete(message: discord.Message):
    """Log deleted messages."""
    if not message.guild or message.author.bot:
        return
    
    # Store deleted message and check log channel in single transaction
    attachments_json = None
    if message.attachments:
        attachments_json = json.dumps([{"url": att.url, "filename": att.filename} for att in message.attachments])
    
    embeds_json = None
    if message.embeds:
        embeds_json = json.dumps([embed.to_dict() for embed in message.embeds])
    
    async with open_db() as db:
        # Store deleted message
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
        
        # Check log channel in same transaction
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_delete' AND enabled=1
        """, (message.guild.id,))
        row = await cur.fetchone()
        await db.commit()
    
    if row:
        log_channel = message.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "🗑️ Message Deleted",
                    f"**Channel:** {_channel_mention_safe(message.channel)}\n"
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
    
    # Store edit and check log channel in single transaction
    async with open_db() as db:
        # Store edit
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
        
        # Check log channel in same transaction
        cur = await db.execute("""
            SELECT channel_id FROM log_channels
            WHERE guild_id=? AND log_type='message_edit' AND enabled=1
        """, (after.guild.id,))
        row = await cur.fetchone()
        await db.commit()
    
    if row:
        log_channel = after.guild.get_channel(row[0])
        if isinstance(log_channel, discord.TextChannel):
            try:
                embed = obsidian_embed(
                    "✏️ Message Edited",
                    f"**Channel:** {_channel_mention_safe(after.channel)}\n"
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
    async with open_db() as db:
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


def _find_similar_commands(typed: str, all_commands: list[str], max_suggestions: int = 3) -> list[str]:
    """Find commands similar to typed (simple prefix/substring match)."""
    typed_lower = typed.lower().strip()
    if not typed_lower:
        return []
    suggestions = []
    for c in all_commands:
        cl = c.lower()
        if cl == typed_lower:
            return []  # Exact match, no suggestion needed
        if cl.startswith(typed_lower) or typed_lower in cl:
            suggestions.append(c)
    # Sort by relevance (prefix matches first, then by length)
    suggestions.sort(key=lambda x: (not x.lower().startswith(typed_lower), len(x)))
    return suggestions[:max_suggestions]


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    """Record per-user slash command usage for /tools my_stats. Best-effort, never raises."""
    try:
        iid = getattr(interaction, "id", None)
        started = _cmd_start_times.pop(int(iid), None) if iid is not None else None
        if started is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms >= 3000:
                qn = (
                    command.qualified_name
                    if hasattr(command, "qualified_name")
                    else getattr(command, "name", "?")
                )
                logger.warning(
                    "[slow_cmd] /%s took %.0f ms (guild=%s user=%s)",
                    qn,
                    elapsed_ms,
                    getattr(interaction.guild, "id", None),
                    getattr(interaction.user, "id", None),
                )
    except Exception:
        pass
    try:
        if interaction.guild is None or interaction.user is None:
            return
        full_name = command.qualified_name if hasattr(command, "qualified_name") else getattr(command, "name", None)
        if not full_name:
            return
        from database import record_command_usage
        await record_command_usage(
            interaction.guild.id,
            interaction.user.id,
            str(full_name),
            now_utc().weekday(),
        )
        from core.command_hints import maybe_send_first_use_hint
        await maybe_send_first_use_hint(interaction, str(full_name))
    except Exception as _err:
        logger.debug(f"[my_stats] failed to record usage: {_err}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle application command errors with user-friendly messages."""
    from core.error_handling import handle_app_command_error

    await handle_app_command_error(
        bot,
        interaction,
        error,
        find_similar_commands=_find_similar_commands,
    )


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
    
    async with open_db() as db:
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
    async with open_db() as db:
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


