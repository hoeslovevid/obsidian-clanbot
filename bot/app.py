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
INTENTS.presences = True
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
            from core.command_sync import should_use_guild_sync

            scope = f"guild {GUILD_ID}" if should_use_guild_sync() else "global"
            print(f"[sync] Skipping command sync — BOT_VERSION {BOT_VERSION} unchanged ({scope})")
            return

        from core.command_sync import sync_app_commands

        try:
            sync_guild_id, self._command_tree_stats = await sync_app_commands(self)
            self._last_command_sync = now_utc()
            self._command_sync_guild_id = sync_guild_id
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
# Slash command start times live in handlers/command_tracking.py
from handlers.command_tracking import mark_command_start

# Incident mode: block non-critical commands for non-mods.
async def incident_mode_check(interaction: discord.Interaction) -> bool:
    mark_command_start(interaction)
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

        try:
            from core.maintenance import maintenance_check
            if not await maintenance_check(interaction):
                return False
        except Exception:
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


from handlers.automod import check_auto_mod
from handlers import vc_panel as _vc_panel_handlers


async def post_vc_panel(guild: discord.Guild, vc: discord.VoiceChannel, owner: discord.Member):
    """Post a VC control panel message."""
    await _vc_panel_handlers.post_vc_panel(bot, guild, vc, owner)


async def update_vc_panel_embed(guild: discord.Guild, vc_id: int, *, force: bool = False) -> None:
    """Edit the VC panel message with live member count and lock status."""
    await _vc_panel_handlers.update_vc_panel_embed(bot, guild, vc_id, force=force)


async def schedule_vc_panel_embed_update(guild: discord.Guild, vc_id: int) -> None:
    """Coalesce voice-triggered VC panel refreshes per guild."""
    await _vc_panel_handlers.schedule_vc_panel_embed_update(bot, guild, vc_id)


# --------------------- Economy Event Handlers ---------------------
@bot.event
async def on_message(message: discord.Message):
    from handlers.message_events import handle_on_message

    await handle_on_message(bot, message)


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


# --------------------- Global auto-defer safety net ---------------------
# Discord invalidates an interaction that isn't acknowledged within 3s. Most
# slow commands defer themselves, but this watchdog defers any straggler so a
# cold DB/Warframe call never surfaces to the user as "This interaction failed".
# Modal-opening commands respond instantly (well under the threshold), so they
# are never affected.
AUTO_DEFER_AFTER_SECONDS = float(os.getenv("AUTO_DEFER_AFTER_SECONDS", "2.5"))


async def _auto_defer_watchdog(interaction: discord.Interaction) -> None:
    """Defer a slash command that hasn't responded yet, to dodge the 3s timeout."""
    try:
        await asyncio.sleep(AUTO_DEFER_AFTER_SECONDS)
        if interaction.response.is_done():
            return
        await interaction.response.defer()
    except (discord.HTTPException, discord.InteractionResponded):
        # Already answered/expired in the race — nothing to do.
        pass
    except Exception as exc:  # never let the watchdog crash the event loop
        logger.debug(f"[auto_defer] watchdog skipped: {exc}")


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
        # Safety net: ensure the command is acknowledged within Discord's 3s window.
        asyncio.create_task(_auto_defer_watchdog(interaction))
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
    from handlers.guild_events import handle_guild_join

    await handle_guild_join(bot, guild)
    activity = _update_status_presence()
    await bot.change_presence(activity=activity, status=discord.Status.online)


@bot.event
async def on_guild_remove(guild: discord.Guild):
    from handlers.guild_events import handle_guild_remove

    await handle_guild_remove(bot, guild)
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


# Cache for achievement definitions moved to handlers/member_events.py


@bot.event
async def on_member_join(member: discord.Member):
    from handlers.member_events import handle_member_join

    await handle_member_join(bot, member)


@bot.event
async def on_member_remove(member: discord.Member):
    from handlers.member_events import handle_member_remove

    await handle_member_remove(bot, member)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    from handlers.reactions import handle_raw_reaction_add

    await handle_raw_reaction_add(bot, payload)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    from handlers.reactions import handle_raw_reaction_remove

    await handle_raw_reaction_remove(bot, payload)


@bot.event
async def on_message_delete(message: discord.Message):
    from handlers.message_logs import handle_message_delete

    await handle_message_delete(bot, message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    from handlers.message_logs import handle_message_edit

    await handle_message_edit(bot, before, after)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    from handlers.message_logs import handle_member_ban

    await handle_member_ban(bot, guild, user)


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    from handlers.command_tracking import handle_app_command_completion

    await handle_app_command_completion(bot, interaction, command)


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
    from core.error_handling import handle_app_command_error

    await handle_app_command_error(
        bot,
        interaction,
        error,
        find_similar_commands=_find_similar_commands,
    )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    from handlers.message_logs import handle_member_update

    await handle_member_update(bot, before, after)


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
        print("  - Presence Intent (PRIVILEGED, recommended)")
        print("\nTo enable:")
        print("1. Go to: https://discord.com/developers/applications/")
        print("2. Select your application")
        print("3. Go to the 'Bot' section")
        print("4. Enable 'SERVER MEMBERS INTENT' under Privileged Gateway Intents")
        print("5. Enable 'MESSAGE CONTENT INTENT' under Privileged Gateway Intents")
        print("6. Enable 'PRESENCE INTENT' (ticket auto-assign + online stats)")
        print("7. Save changes and restart the bot\n")
        print("="*60 + "\n")
        raise
    except KeyboardInterrupt:
        print("\n[shutdown] Bot stopped by user")
    except Exception as e:
        print(f"\n[error] Bot crashed: {e}")
        raise


