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
from config import (
    TOKEN, GUILD_ID, MOD_ROLE_NAME, BOT_STATUS, TIMEZONE, DB_PATH,
    BOT_VERSION, BOT_CHANGELOG,
    TEMP_VC_CATEGORY_ID, TEMP_VC_CATEGORY_NAME, CREATE_VC_NAME,
    VOICE_IDLE_DELETE_MINUTES, VC_CLEANUP_INTERVAL_MINUTES,
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
    "bot", "check_auto_mod", "post_vc_panel", "log_complaint_action",
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
from utils import obsidian_embed, extract_id, get_mod_role, is_mod, parse_time_natural, display_case_status
from database import (
    get_user_balance, add_coins, remove_coins, transfer_coins,
    get_user_xp, add_xp, calculate_level, xp_for_level, xp_for_next_level,
    get_guild_setting, set_guild_setting, now_utc, init_db
)
from channels import (
    resolve_channel_id, find_or_create_text_channel,
    resolve_temp_vc_category, ensure_join_to_create_channel, ensure_core_channels,
    delete_temp_vc_and_panel, delete_vc_panel_message
)
from modals import RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal, ComplaintModal, RequestInfoModal
from views import VCPanelView, ComplaintPanel, ComplaintModView, RSVPView, SetLimitView, SetLimitSelect
# tasks and version_tracking: lazy-import to defer ~2k lines until needed
def detect_and_update_version(*args, **kwargs):
    """Lazy wrapper - loads version_tracking only when called (e.g. /force_version_update)."""
    from version_tracking import detect_and_update_version as _fn
    return _fn(*args, **kwargs)




# Global tracking set for modal submissions to prevent duplicates
_processed_modal_submissions = set()

# --------------------- Bot ---------------------
class ClanBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.start_time = now_utc()

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
                print(f"[sync] Synced {len(commands_list)} top-level commands/groups to guild {GUILD_ID}")
                print(f"[sync] Top-level: {', '.join(commands_list)}")
                
                # Verify groups and their subcommands
                total_subcommands = 0
                for cmd in self.tree.get_commands(guild=guild):
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
        except discord.app_commands.errors.CommandSyncFailure as e:
            print(f"[sync] Failed to sync commands: {e}")
            # Try to extract which command failed
            if hasattr(e, 'errors') and e.errors:
                print(f"[sync] Error details: {e.errors}")
            # Also check the commands that were being synced
            if hasattr(e, 'commands'):
                print(f"[sync] Commands being synced: {len(e.commands) if e.commands else 0}")
                # Try to find commands with choices that might be too long
                for cmd in (e.commands or []):
                    if isinstance(cmd, app_commands.Command):
                        # Check parameters
                        for param in cmd.parameters:
                            if hasattr(param, 'choices') and param.choices:
                                for choice in param.choices:
                                    if len(choice.name) >= 25:
                                        print(f"[sync] ERROR: Command '{cmd.name}' has choice '{choice.name}' with {len(choice.name)} characters!")
                    elif isinstance(cmd, app_commands.Group):
                        for subcmd in cmd.commands:
                            for param in subcmd.parameters:
                                if hasattr(param, 'choices') and param.choices:
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
from commands_loader import load_all_commands
load_all_commands(bot)

# --------------------- Global app command checks ---------------------
# Incident mode: block non-critical commands for non-mods.
async def incident_mode_check(interaction: discord.Interaction) -> bool:
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
        }

        # Any command under /mod is allowed
        if qualified == "mod" or qualified.startswith("mod "):
            return True

        if qualified in allowed:
            return True

        msg = await get_guild_setting(interaction.guild.id, "incident_mode_message")
        reason = msg.strip() if msg else "Incident mode is active. Please try again later."
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=obsidian_embed("🚨 Incident Mode", reason, color=discord.Color.orange(), client=bot),
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
        "Voice Channel Control",
        f"**Channel:** {vc.mention}\n"
        f"**Owner:** {owner.mention}\n\n"
        "Configure your voice channel using the controls below.\n"
        "_Administrators retain oversight._",
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

    # Bot mention: hybrid response (keywords + optional AI)
    if message.guild.me in message.mentions:
        try:
            from mention_chat import get_mention_reply
            reply = await get_mention_reply(
                message.content,
                message.guild.me.id,
                OPENAI_API_KEY,
            )
            await message.reply(reply, mention_author=False)
            return  # Don't process economy for mention-only messages
        except discord.Forbidden:
            pass

    # Ticket enhancements: track ticket SLA / activity timestamps
    # Only do DB work if message is inside the Tickets category
    try:
        if isinstance(message.channel, discord.TextChannel) and message.channel.category and message.channel.category.name == "Tickets":
            now_iso = now_utc().isoformat()
            is_staff = isinstance(message.author, discord.Member) and is_mod(message.author)
            async with aiosqlite.connect(DB_PATH) as db:
                # Update last activity; if staff and first_response_at missing, set it
                await db.execute(
                    """
                    UPDATE tickets
                    SET last_activity_at=?,
                        first_response_at=CASE
                            WHEN ?=1 AND (first_response_at IS NULL OR first_response_at='') THEN ?
                            ELSE first_response_at
                        END
                    WHERE guild_id=? AND channel_id=? AND status='open'
                    """,
                    (now_iso, 1 if is_staff else 0, now_iso, message.guild.id, message.channel.id),
                )
                await db.commit()
    except Exception:
        # Never break message handling because of ticket tracking
        pass
    
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
            
            # Send level-up announcement to configured channel
            from utils import send_levelup_announcement
            await send_levelup_announcement(message.guild, message.author, level, xp, total_xp)
            
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
        
        # Check for level milestones and achievements (optimized - single query for activity stats)
        xp, level, total_xp = await get_user_xp(message.guild.id, message.author.id)
        from database import check_and_record_milestone, check_and_unlock_achievement
        
        # Initialize achievements if needed (cached)
        global _achievement_definitions_initialized
        if not _achievement_definitions_initialized:
            from database import initialize_achievement_definitions, initialize_badge_definitions, initialize_title_definitions
            await initialize_achievement_definitions()
            await initialize_badge_definitions()
            await initialize_title_definitions()
            _achievement_definitions_initialized = True
        
        # Batch database operations - get message count and update in one transaction
        async with aiosqlite.connect(DB_PATH) as db:
            # Get current message count
            cur = await db.execute("""
                SELECT messages_sent FROM activity_stats
                WHERE guild_id=? AND user_id=?
            """, (message.guild.id, message.author.id))
            row = await cur.fetchone()
            message_count = row[0] if row else 0
            
            # Update message count
            await db.execute("""
                INSERT INTO activity_stats (guild_id, user_id, messages_sent, last_activity_date)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    messages_sent = messages_sent + 1,
                    last_activity_date = excluded.last_activity_date
            """, (message.guild.id, message.author.id, now_utc().isoformat()))
            await db.commit()
        
        new_message_count = message_count + 1
        
        # Check level milestones
        level_milestones = [10, 25, 50, 100]
        for milestone_level in level_milestones:
            if level >= milestone_level:
                milestone_achieved = await check_and_record_milestone(
                    message.guild.id, message.author.id, "level", milestone_level
                )
                if milestone_achieved:
                    achievement_id = f"level_{milestone_level}"
                    await check_and_unlock_achievement(message.guild.id, message.author.id, achievement_id, bot)
        
        # Check message count milestones
        message_milestones = [1, 100, 1000, 10000]
        for milestone_count in message_milestones:
            if new_message_count >= milestone_count:
                milestone_achieved = await check_and_record_milestone(
                    message.guild.id, message.author.id, "message_count", milestone_count
                )
                if milestone_achieved:
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
    vc_name = f"{member.display_name} • Squad"
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
        reason="Join-to-create temp VC",
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
                            f"**Staff request:**\n{question_val}\n\n"
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
                mention = mod_role.mention if mod_role else "**Administrators**"

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
                    mention = mod_role.mention if mod_role else "**Administrators**"

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
                    return await interaction.response.send_message("Only the squad owner (or an Administrator) may do that.", ephemeral=True)

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

                    await vc.edit(overwrites=overwrites, reason="VC panel action")

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
        
        # Application panel: start application
        # Note: This is handled by ApplicationPanelView.start_application callback
        # The view callback is called automatically by discord.py when the button is clicked
        # We don't need to handle it here to avoid duplicate processing
        # If the view callback doesn't exist (e.g., after bot restart), the button won't work anyway
        # So we skip handling it here to avoid double-defer errors
        
        # Applications: approve or reject
        # Note: This is handled by ApplicationManageView callbacks (approve_button, reject_button)
        # The views are registered with bot.add_view() in on_ready, so discord.py will automatically
        # call the view callbacks when buttons are clicked. We don't need to handle it here.
        # The view callbacks handle their own interaction acknowledgment (defer for approve, send_modal for reject).

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
    """Update bot presence with /help hint and guild count."""
    guild_count = len(bot.guilds)
    activity = discord.Activity(
        type=discord.ActivityType.playing,
        name=f"/help • {guild_count} server{'s' if guild_count != 1 else ''}"
    )
    return activity


@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} ({bot.user.id})")
    
    activity = _update_status_presence()
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"[ready] Status set: Watching {activity.name}")

    guild_names = [g.name for g in bot.guilds]
    shown = guild_names[:15]
    suffix = f", ... and {len(guild_names) - 15} more" if len(guild_names) > 15 else ""
    print(f"[ready] Servers ({len(guild_names)}): {', '.join(shown)}{suffix}")

    # Parallelize startup tasks for faster initialization
    async def setup_guild_channels():
        """Setup channels for all guilds in parallel."""
        tasks = []
        for g in bot.guilds:
            tasks.append(ensure_core_channels(g))
            tasks.append(ensure_join_to_create_channel(g))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                guild_idx = i // 2
                if guild_idx < len(bot.guilds):
                    print(f"[startup] Ensure failed in {bot.guilds[guild_idx].name}: {result}")
    
    async def setup_background_tasks():
        """Setup background tasks (lazy-import defers tasks.py ~1700 lines until ready)."""
        try:
            from tasks import setup_tasks
            tasks_dict = setup_tasks(bot)
            print(f"[ready] Background tasks initialized: {len(tasks_dict)} tasks")
        except Exception as e:
            print(f"[ready] ERROR: Failed to setup background tasks: {e}")
            import traceback
            traceback.print_exc()
    
    async def register_persistent_views():
        """Register all persistent views in parallel."""
        # Basic views
        bot.add_view(ComplaintPanel())
        bot.add_view(RSVPView())
        
        # Collect all view data in parallel
        async def get_all_view_data():
            """Fetch all view data in a single query batch."""
            async with aiosqlite.connect(DB_PATH) as db:
                # Fetch all data in parallel queries
                vc_cur = await db.execute("SELECT guild_id, channel_id FROM temp_vcs")
                vc_data = await vc_cur.fetchall()
                
                lfg_cur = await db.execute("SELECT id FROM lfg_posts WHERE status='OPEN'")
                lfg_data = await lfg_cur.fetchall()
                
                complaint_cur = await db.execute("SELECT case_id FROM complaints WHERE status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')")
                complaint_data = await complaint_cur.fetchall()
                
                suggestion_cur = await db.execute("SELECT id FROM suggestions WHERE status='PENDING'")
                suggestion_data = await suggestion_cur.fetchall()
                
                app_cur = await db.execute("SELECT id FROM applications WHERE status='PENDING'")
                app_data = await app_cur.fetchall()
                
                panel_cur = await db.execute("SELECT guild_id, panel_message_id FROM application_settings WHERE panel_message_id IS NOT NULL")
                panel_data = await panel_cur.fetchall()
                
                giveaway_cur = await db.execute("SELECT id FROM giveaways WHERE ended = 0")
                giveaway_data = await giveaway_cur.fetchall()
                
                trading_cur = await db.execute("SELECT id, user_id FROM trading_posts WHERE status='ACTIVE'")
                trading_data = await trading_cur.fetchall()

                ticket_cur = await db.execute(
                    "SELECT id, ticket_id, control_message_id FROM tickets WHERE status='open' AND control_message_id IS NOT NULL"
                )
                ticket_data = await ticket_cur.fetchall()
                
                return {
                    'vc': vc_data,
                    'lfg': lfg_data,
                    'complaints': complaint_data,
                    'suggestions': suggestion_data,
                    'applications': app_data,
                    'panels': panel_data,
                    'giveaways': giveaway_data,
                    'trading': trading_data,
                    'tickets': ticket_data,
                }
        
        view_data = await get_all_view_data()
        
        # Register views (non-blocking)
        for (guild_id, channel_id) in view_data['vc']:
            try:
                bot.add_view(VCPanelView(int(channel_id)))
            except Exception:
                pass
        
        for (lfg_id,) in view_data['lfg']:
            try:
                from commands.warframe.lfg import LFGView
                bot.add_view(LFGView(int(lfg_id)))
            except Exception:
                pass
        
        for (case_id,) in view_data['complaints']:
            try:
                bot.add_view(ComplaintModView(str(case_id)))
            except Exception:
                pass
        
        for (suggestion_id,) in view_data['suggestions']:
            try:
                from commands.suggestions.manage_suggestions import SuggestionView
                bot.add_view(SuggestionView(int(suggestion_id)))
            except Exception:
                pass
        
        for (application_id,) in view_data['applications']:
            try:
                from views import ApplicationManageView
                bot.add_view(ApplicationManageView(int(application_id)))
            except Exception:
                pass
        
        for (guild_id, panel_message_id) in view_data['panels']:
            try:
                from views import ApplicationPanelView
                bot.add_view(ApplicationPanelView(guild_id))
            except Exception:
                pass
        
        for (giveaway_id,) in view_data['giveaways']:
            try:
                from views import GiveawayView
                bot.add_view(GiveawayView(giveaway_id))
            except Exception as e:
                logger.debug(f"[ready] Error re-registering giveaway view {giveaway_id}: {e}")
        
        for (listing_id, user_id) in view_data['trading']:
            try:
                from views import TradingPostView
                bot.add_view(TradingPostView(int(listing_id), int(user_id)))
            except Exception:
                pass

        # Ticket control panels (per-ticket persistent views)
        for (ticket_db_id, ticket_id, control_message_id) in view_data.get('tickets', []):
            try:
                from commands.tickets.ticket import TicketControlView
                if control_message_id:
                    bot.add_view(TicketControlView(int(ticket_db_id), str(ticket_id)), message_id=int(control_message_id))
            except Exception:
                pass
    
    # Run setup tasks in parallel
    await asyncio.gather(
        setup_guild_channels(),
        setup_background_tasks(),
        register_persistent_views(),
        return_exceptions=True
    )

    
    # Verify update log settings and version tracking (parallel)
    async def verify_settings():
        """Verify update log settings and version tracking."""
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
    
    async def init_achievements():
        """Initialize achievement definitions (cached)."""
        global _achievement_definitions_initialized
        try:
            from database import initialize_achievement_definitions, initialize_badge_definitions, initialize_title_definitions
            await initialize_achievement_definitions()
            await initialize_badge_definitions()
            await initialize_title_definitions()
            _achievement_definitions_initialized = True
            logger.info("[ready] Achievement definitions initialized")
        except Exception as e:
            logger.error(f"[ready] Error initializing achievements: {e}", exc_info=True)
    
    # Update application profile (description, tags) for bot profile display
    async def update_app_profile():
        try:
            from app_profile import update_app_profile_metadata
            await update_app_profile_metadata()
        except Exception as e:
            logger.debug(f"[ready] App profile update skipped: {e}")

    # Run verification tasks in parallel
    await asyncio.gather(
        verify_settings(),
        init_achievements(),
        update_app_profile(),
        return_exceptions=True
    )
    
    # Wait a bit for commands to fully sync, then check and post automatic update logs (non-blocking)
    async def check_updates():
        """Check for updates in background (lazy-import defers version_tracking until ready)."""
        try:
            from version_tracking import check_and_post_updates
            logger.info("[ready] Waiting for commands to sync, then checking for automatic updates...")
            await asyncio.sleep(5)  # Give commands more time to fully register and sync with Discord
            logger.info("[ready] Starting update check...")
            await check_and_post_updates(bot)
            logger.info("[ready] Automatic update check completed")
        except Exception as e:
            logger.error(f"[ready] Error during automatic update check: {e}", exc_info=True)
    
    # Run update check in background (non-blocking)
    asyncio.create_task(check_updates())
    
    # Re-register reaction roles for all messages (optimized - batch fetch reactions)
    async def restore_reaction_roles():
        """Restore reaction roles in background (non-blocking)."""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Get all reaction role messages with their emojis in one query
                cur = await db.execute("""
                    SELECT DISTINCT message_id, channel_id, 
                           GROUP_CONCAT(emoji, ',') as emojis
                    FROM reaction_roles
                    GROUP BY message_id, channel_id
                """)
                reaction_messages = await cur.fetchall()
            
            # Process in batches to avoid rate limits
            for message_id, channel_id, emojis_str in reaction_messages:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        try:
                            message = await channel.fetch_message(message_id)
                            emojis = emojis_str.split(',') if emojis_str else []
                            
                            # Re-add reactions if they're missing (batch)
                            for emoji_str in emojis:
                                try:
                                    if not any(str(r.emoji) == emoji_str for r in message.reactions):
                                        await message.add_reaction(emoji_str)
                                except Exception:
                                    pass
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        except Exception as e:
                            logger.debug(f"[ready] Error restoring reaction roles for message {message_id}: {e}")
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[ready] Error in reaction role restoration: {e}")
    
    # Run reaction role restoration in background (non-blocking)
    asyncio.create_task(restore_reaction_roles())


# Cache for achievement definitions (avoid repeated initialization)
_achievement_definitions_initialized = False

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
        if member_count % 100 == 0 or member_count in [50, 250, 500, 1000, 2500, 5000, 10000]:
            await check_and_celebrate_milestone(member.guild, "member_count", member_count)
    except Exception as e:
        logger.error(f"[milestones] Error checking member count milestone: {e}")
    
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
    formatted_message = formatted_message.replace("{member_count}", str(member.guild.member_count or 0))
    
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
    
    async with aiosqlite.connect(DB_PATH) as db:
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
    
    # Store edit and check log channel in single transaction
    async with aiosqlite.connect(DB_PATH) as db:
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


async def _send_error_reply(interaction: discord.Interaction, message: str, ephemeral: bool = True, action_hint: Optional[str] = None):
    """Send an error reply with consistent embed, using followup if response was already sent."""
    from utils import error_embed
    emb = error_embed("Error", message, action_hint=action_hint, client=interaction.client)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=emb, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=emb, ephemeral=ephemeral)
    except Exception:
        pass  # Silently fail if we can't send (e.g. DMs closed)


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


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle application command errors with user-friendly messages."""
    error_type_name = type(error).__name__
    
    if error_type_name == "CommandNotFound":
        command_name = str(error).split("'")[1] if "'" in str(error) else "unknown"
        moved_commands = {"sync_commands": "general sync_commands"}
        if command_name in moved_commands:
            logger.debug(f"[commands] CommandNotFound for '{command_name}' - Discord cache will update")
            return
        # Typo suggestions: collect commands and find similar
        try:
            all_names = []
            for cmd in interaction.client.tree.get_commands(guild=interaction.guild):
                if isinstance(cmd, app_commands.Group):
                    all_names.append(cmd.name)
                    for sub in cmd.commands:
                        if isinstance(sub, app_commands.Group):
                            for g in sub.commands:
                                all_names.append(cmd.name + " " + sub.name + " " + g.name)
                        else:
                            all_names.append(cmd.name + " " + sub.name)
                else:
                    all_names.append(cmd.name)
            similar = _find_similar_commands(command_name, all_names)
            if similar:
                hint = f" Did you mean: **{'** or **'.join(similar[:3])}**?"
                await _send_error_reply(interaction, f"Unknown command `{command_name}`.{hint}")
                return
        except Exception:
            pass
        logger.debug(f"[commands] CommandNotFound: {error}")
        return
    
    if error_type_name == "CommandSignatureMismatch":
        logger.debug(f"[commands] CommandSignatureMismatch - Discord cache is out of sync.")
        return
    
    # User-friendly messages for common errors
    # Friendlier rate limit (cooldown) messages
    if error_type_name == "CommandOnCooldown":
        retry_after = getattr(error, "retry_after", None) or 0
        if retry_after >= 60:
            msg = f"You can use this again in **{int(retry_after // 60)} minute(s)**."
        elif retry_after >= 1:
            msg = f"You can use this again in **{int(retry_after)} second(s)**."
        else:
            msg = "Please wait a moment before trying again."
        await _send_error_reply(interaction, msg, action_hint="Use /help to explore other commands.")
        return

    if error_type_name in ("CheckFailure", "MissingRole", "MissingAnyRole"):
        await _send_error_reply(interaction, "You don't have permission to use this command.", action_hint="Ask an administrator if you need access.")
        return

    if error_type_name == "MissingPermissions":
        # User lacks permissions - show which ones if available
        perms = getattr(error, "missing_permissions", None) or []
        if perms:
            names = [str(p).replace("_", " ").title() for p in perms]
            await _send_error_reply(interaction, f"You need: **{', '.join(names)}**. Ask an admin to grant them.")
        else:
            await _send_error_reply(interaction, "You don't have permission to use this command.")
        return

    if error_type_name in ("Forbidden", "HTTPException"):
        err_msg = str(error)
        if "429" in err_msg or "rate limit" in err_msg.lower():
            await _send_error_reply(interaction, "Discord is rate limiting requests. Please wait a minute and try again.", action_hint="This usually resolves quickly.")
        elif "Missing Access" in err_msg or "50013" in err_msg:
            await _send_error_reply(interaction, "I need additional permissions (e.g. **Manage Messages**, **Send Messages**). Ask an admin to grant them for this channel.")
        elif "Unknown Channel" in err_msg:
            await _send_error_reply(interaction, "That channel no longer exists.")
        else:
            await _send_error_reply(interaction, "An error occurred. Please try again later.")
        logger.warning(f"[commands] Discord API error: {error}")
        return

    # CommandInvokeError wraps the real exception (e.g. Forbidden from channel.send)
    if error_type_name == "CommandInvokeError" and hasattr(error, "original"):
        orig = error.original
        orig_name = type(orig).__name__
        if orig_name in ("Forbidden", "HTTPException"):
            err_msg = str(orig)
            status = getattr(orig, "status", None)
            if status == 429 or "429" in err_msg or "rate limit" in err_msg.lower():
                retry_after = getattr(orig, "retry_after", 60)
                await _send_error_reply(interaction, f"Discord is rate limiting. Wait **{int(retry_after)}s** and try again.", action_hint="This usually resolves quickly.")
            elif "Missing Access" in err_msg or "50013" in err_msg:
                await _send_error_reply(interaction, "I need additional permissions (e.g. **Manage Messages**, **Send Messages**). Ask an admin to grant them for this channel.")
            elif "Unknown Channel" in err_msg:
                await _send_error_reply(interaction, "That channel no longer exists.")
            else:
                await _send_error_reply(interaction, "An error occurred. Please try again later.")
            logger.warning(f"[commands] Command invoke error: {orig}")
            return
    
    # Unexpected errors: inform user and log
    logger.error(f"[commands] Unhandled command error: {error}", exc_info=error)
    await _send_error_reply(interaction, "Something went wrong. Please try again later.")


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
