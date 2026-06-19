"""
Background tasks for the bot (internal module).

All tasks are defined here as closures inside setup_tasks(bot).
Import setup_tasks from the tasks package: ``from tasks import setup_tasks``
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord
from discord.ext import tasks  # type: ignore

from database import DB_PATH, now_utc, get_guild_setting, set_guild_setting, get_quieter_mode, add_coins, add_xp, get_user_xp, increment_activity_voice_minutes, check_voice_lifetime_achievements
from core.channels import resolve_channel_id, delete_temp_vc_and_panel
from api.warframe_api import get_baro_status, get_all_cycles, fetch_invasions, fetch_archon_hunt_data, fetch_events_data, fetch_alerts, fetch_duviri_circuit
from core.utils import obsidian_embed, ECONOMY_ENABLED, COINS_PER_MINUTE_VOICE, MIN_VOICE_MINUTES_FOR_REWARD, XP_ENABLED, XP_PER_MINUTE_VOICE
from core.safe_send import safe_dm
from tasks.wf_notify import (
    check_and_notify_baro_arrival,
    clear_baro_live_embed_cache,
    get_baro_embed_builder,
    get_baro_live_embed_cache,
)

# ---------------------------------------------------------------------------
# Notify channel health-check helper
# ---------------------------------------------------------------------------
# Tracks (guild_id, channel_id) pairs already warned this session to avoid
# spamming the guild owner every loop iteration.
_warned_broken_channels: set[tuple[int, int]] = set()

CYCLE_LIVE_UPDATE_MINUTES = max(3, min(15, int(os.getenv("CYCLE_LIVE_UPDATE_MINUTES", "5"))))


async def _warn_broken_channel(
    guild: discord.Guild, channel_id: int, feature: str
) -> None:
    """DM the guild owner once when a notification channel is missing or inaccessible."""
    key = (guild.id, channel_id)
    if key in _warned_broken_channels:
        return
    _warned_broken_channels.add(key)
    owner = guild.owner
    if not owner:
        return
    try:
        await owner.send(
            f"\u26a0\ufe0f **{guild.name}** \u2014 the **{feature}** notification channel "
            f"(ID: `{channel_id}`) could not be found or is no longer accessible.\n"
            f"Please reconfigure it with the appropriate `/wfnotify` or setup command."
        )
    except Exception:
        pass  # DMs disabled or bot can't reach owner


logger = logging.getLogger(__name__)

# Import config from environment
VOICE_IDLE_DELETE_MINUTES = int(os.getenv("VOICE_IDLE_DELETE_MINUTES", "5"))
VC_CLEANUP_INTERVAL_MINUTES = int(os.getenv("VC_CLEANUP_INTERVAL_MINUTES", "2"))
VOICE_REWARD_INTERVAL_MINUTES = int(os.getenv("VOICE_REWARD_INTERVAL_MINUTES", "1"))
EVENT_REMINDER_MINUTES_BEFORE = int(os.getenv("EVENT_REMINDER_MINUTES_BEFORE", "60"))
EVENT_REMINDER_LOOP_MINUTES = int(os.getenv("EVENT_REMINDER_LOOP_MINUTES", "1"))
VOICE_PANEL_CHANNEL_ID = int(os.getenv("VOICE_PANEL_CHANNEL_ID", "0") or "0")
VOICE_PANEL_CHANNEL_NAME = os.getenv("VOICE_PANEL_CHANNEL_NAME", "obsidian-console")
COMPLAINTS_CHANNEL_ID = int(os.getenv("COMPLAINTS_CHANNEL_ID", "0") or "0")
COMPLAINTS_CHANNEL_NAME = os.getenv("COMPLAINTS_CHANNEL_NAME", "inheritor-docket")
EVENTS_CHANNEL_ID = int(os.getenv("EVENTS_CHANNEL_ID", "0") or "0")
EVENTS_CHANNEL_NAME = os.getenv("EVENTS_CHANNEL_NAME", "ops-board")



def setup_tasks(bot):
    """Set up all background tasks. Must be called after bot is created."""
    
    @tasks.loop(minutes=VC_CLEANUP_INTERVAL_MINUTES)
    async def temp_vc_cleanup():
        # Item 47: expire stale revival vote messages each cycle.
        try:
            from commands.voice.vc import expire_pending_revivals
            await expire_pending_revivals(bot)
        except Exception as e:
            logger.debug(f"[vc-revival] expire pass failed: {e}")

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
                    await delete_temp_vc_and_panel(guild, int(channel_id), reason="Cleanup missing VC", bot=bot)
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
                    # Item 47: post a revival-vote message in the panel channel
                    # BEFORE we delete the VC, so the metadata is still readable.
                    try:
                        from commands.voice.vc import _record_revival_intent
                        from core.channels import resolve_channel_id
                        from bot import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
                        panel_ch_id = await resolve_channel_id(
                            guild, "voice_panel_channel_id",
                            VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME,
                        )
                        panel_ch = guild.get_channel(panel_ch_id) if panel_ch_id else None
                        if isinstance(panel_ch, discord.TextChannel):
                            await _record_revival_intent(guild, vc, log_channel=panel_ch)
                    except Exception as e:
                        logger.debug(f"[vc-revival] could not record revival intent: {e}")
                    await delete_temp_vc_and_panel(guild, vc.id, reason="Temp VC idle cleanup", bot=bot)

    @temp_vc_cleanup.before_loop
    async def before_temp_vc_cleanup():
        await bot.wait_until_ready()

    @tasks.loop(minutes=EVENT_REMINDER_LOOP_MINUTES)
    async def event_reminder_loop():
        try:
            from commands.events.event_create import _ensure_event_columns

            await _ensure_event_columns()
        except Exception:
            pass

        try:
            from tasks.event_loops import run_event_reminder_cycle

            await run_event_reminder_cycle(bot)
        except Exception as e:
            logger.error(f"Error in event_reminder_loop: {e}", exc_info=True)

    @event_reminder_loop.before_loop
    async def before_event_reminder_loop():
        await bot.wait_until_ready()
        await asyncio.sleep(12)

    @tasks.loop(hours=1)
    async def recurring_event_loop():
        """Create events from recurring templates when scheduled time matches."""
        try:
            from tasks.event_loops import run_recurring_event_cycle

            await run_recurring_event_cycle(bot)
        except Exception as e:
            logger.error(f"Error in recurring_event_loop: {e}", exc_info=True)

    @recurring_event_loop.before_loop
    async def before_recurring_event_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def event_end_loop():
        """Post end-of-event recaps and mark events ended."""
        try:
            from tasks.event_loops import run_event_end_cycle

            await run_event_end_cycle(bot)
        except Exception as e:
            logger.error(f"Error in event_end_loop: {e}", exc_info=True)

    @event_end_loop.before_loop
    async def before_event_end_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def event_rsvp_reminder_loop():
        """Item 66 — DM ✅ RSVPed users when their event is 30-35 minutes away.

        Guild toggle: ``event_rsvp_dm_reminders_enabled`` (default ON).
        User opt-out: ``user_event_dm:{user_id}`` (default ON).
        Tracked in ``event_dm_reminders_sent`` so a 5-minute loop overlap
        can't DM the same user twice for the same event.
        """
        try:
            from tasks.event_loops import run_event_rsvp_reminder_cycle

            await run_event_rsvp_reminder_cycle(bot)
        except Exception as e:
            logger.error(f"Error in event_rsvp_reminder_loop: {e}", exc_info=True)

    @event_rsvp_reminder_loop.before_loop
    async def before_event_rsvp_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def inactive_role_sweep_loop():
        """Item 83 — daily sweep that adds the configured inactive role to
        members whose ``activity_stats.last_activity_date`` (or join date when
        no activity row exists) is older than the per-guild threshold."""
        try:
            from commands.moderation.inactive_role import (
                get_inactive_role_id, get_inactive_threshold_days, _last_activity_for,
                was_inactive_warned, mark_inactive_warned,
            )
            from core.utils import obsidian_embed
            for guild in bot.guilds:
                try:
                    role_id = await get_inactive_role_id(guild.id)
                    if not role_id:
                        continue
                    role = guild.get_role(role_id)
                    if role is None:
                        continue
                    me = guild.me
                    if me is None or role >= me.top_role:
                        # Discord won't let us assign a role at/above our top role
                        continue
                    threshold = await get_inactive_threshold_days(guild.id)
                    cutoff = now_utc() - timedelta(days=threshold)
                    warn_days = max(1, int(threshold * 0.75))
                    warn_cutoff = now_utc() - timedelta(days=warn_days)
                    tagged = 0
                    warned = 0
                    for member in guild.members:
                        if member.bot or role in member.roles:
                            continue
                        last = await _last_activity_for(guild.id, member.id)
                        if last is None:
                            joined = member.joined_at
                            if joined is None:
                                continue
                            ref_dt = joined if joined.tzinfo else joined.replace(tzinfo=timezone.utc)
                        else:
                            ref_dt = last
                        if ref_dt < cutoff:
                            try:
                                await member.add_roles(role, reason=f"Inactive {threshold}d (auto-sweep)")
                                tagged += 1
                            except (discord.Forbidden, discord.HTTPException) as e:
                                logger.debug(f"[inactive_role] could not tag {member.id}: {e}")
                        elif ref_dt < warn_cutoff and not await was_inactive_warned(guild.id, member.id):
                            days_left = max(1, threshold - warn_days)
                            try:
                                dm = obsidian_embed(
                                    "⚠️ Inactivity Notice",
                                    f"You haven't been active in **{guild.name}** for about **{warn_days}** days.\n\n"
                                    f"In **~{days_left}** more days you may receive the {role.mention} role "
                                    f"(threshold: **{threshold}** days).\n\n"
                                    f"_Chat, use commands, or join voice to stay active._",
                                    color=discord.Color.orange(),
                                    client=bot,
                                )
                                await safe_dm(member,embed=dm)
                                await mark_inactive_warned(guild.id, member.id)
                                warned += 1
                            except (discord.Forbidden, discord.HTTPException):
                                await mark_inactive_warned(guild.id, member.id)
                    if tagged:
                        logger.info(f"[inactive_role] tagged {tagged} member(s) in {guild.name}")
                    if warned:
                        logger.info(f"[inactive_role] warned {warned} member(s) in {guild.name}")
                except Exception as e:
                    logger.warning(f"[inactive_role] guild {guild.id} sweep failed: {e}")
        except Exception as e:
            logger.error(f"[inactive_role] sweep loop error: {e}", exc_info=True)

    @inactive_role_sweep_loop.before_loop
    async def before_inactive_role_sweep_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def goal_progress_loop():
        """Item 72 — recompute server-wide goal progress every 15 minutes."""
        try:
            from commands.general.server_goals import evaluate_active_goal
            for guild in bot.guilds:
                try:
                    await evaluate_active_goal(guild, bot)
                except Exception as e:
                    logger.debug(f"[server_goals] guild {guild.id} eval failed: {e}")
        except Exception as e:
            logger.error(f"[server_goals] goal_progress_loop error: {e}", exc_info=True)

    @goal_progress_loop.before_loop
    async def before_goal_progress_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=VOICE_REWARD_INTERVAL_MINUTES)
    async def voice_reward_loop():
        """Award coins to users based on voice channel activity."""

        try:
            from tasks.economy_loops import run_voice_reward_cycle

            await run_voice_reward_cycle(bot)
        except Exception as e:
            logger.error(f"Error in voice_reward_loop: {e}", exc_info=True)

    @voice_reward_loop.before_loop
    async def before_voice_reward_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)  # Check every hour for Baro
    async def baro_check_loop():
        """Check for Baro Ki'Teer arrivals and send notifications."""
        try:
            await check_and_notify_baro_arrival(bot, warned_channels=_warned_broken_channels)
        except Exception as e:
            logger.error(f"Error in baro_check_loop: {e}", exc_info=True)

    @baro_check_loop.before_loop
    async def before_baro_check_loop():
        await bot.wait_until_ready()
        await asyncio.sleep(24)

    @tasks.loop(minutes=5)  # Live countdown — Discord :R timestamps update client-side; 5m is enough for text countdowns
    async def baro_live_update_loop():
        """Update live Baro messages with current time remaining."""
        try:
            is_active, baro_data = await get_baro_status()
            
            if not is_active or not baro_data:
                # Baro is not active, clean up all live messages
                clear_baro_live_embed_cache()
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM baro_live_messages")
                    await db.commit()
                return
            
            # Get all live messages
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT guild_id, channel_id, message_id, expiry_time
                    FROM baro_live_messages
                """)
                messages = await cur.fetchall()
            
            # Update each message
            for guild_id, channel_id, message_id, expiry_time_str in messages:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        # Guild not found, remove from database
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                                (guild_id, channel_id, message_id)
                            )
                            await db.commit()
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        # Channel not found or wrong type, remove from database
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                                (guild_id, channel_id, message_id)
                            )
                            await db.commit()
                        continue
                    
                    try:
                        message = await channel.fetch_message(message_id)
                    except discord.NotFound:
                        # Message deleted, remove from database
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                                (guild_id, channel_id, message_id)
                            )
                            await db.commit()
                        continue
                    
                    # Check if Baro has expired
                    try:
                        expiry_time = datetime.fromisoformat(expiry_time_str.replace('Z', '+00:00'))
                        if expiry_time <= datetime.now(timezone.utc):
                            # Baro has expired, remove from database
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute(
                                    "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                                    (guild_id, channel_id, message_id)
                                )
                                await db.commit()
                            continue
                    except Exception:
                        pass
                    
                    # Rebuild embed with updated time
                    build_baro_embed = get_baro_embed_builder()
                    updated_embed = build_baro_embed(baro_data, True, bot)

                    # Skip edit when content unchanged (reduces PATCH spam / 429s)
                    desc_key = (updated_embed.description or "") + (updated_embed.title or "")
                    cache_key = (guild_id, channel_id, message_id)
                    baro_cache = get_baro_live_embed_cache()
                    if baro_cache.get(cache_key) == desc_key:
                        continue

                    from core.safe_message_edit import safe_message_edit

                    await safe_message_edit(message, embed=updated_embed)
                    baro_cache[cache_key] = desc_key
                    
                except discord.Forbidden:
                    # Missing permissions, remove from database
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "DELETE FROM baro_live_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
                            (guild_id, channel_id, message_id)
                        )
                        await db.commit()
                except Exception as e:
                    logger.error(f"Error updating Baro live message {message_id} in {guild_id}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in baro_live_update_loop: {e}", exc_info=True)

    @baro_live_update_loop.before_loop
    async def before_baro_live_update_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=CYCLE_LIVE_UPDATE_MINUTES)
    async def cycle_live_update_loop():
        """Update pinned live cycle panels in place."""
        try:
            if not bot.is_ready():
                return

            from core.cycles_live import (
                build_cycles_live_embed,
                cycles_embed_fingerprint,
                delete_cycle_live_message,
                get_cycle_live_embed_cache,
            )
            from core.safe_message_edit import safe_message_edit

            cycles_data = await get_all_cycles()
            if not cycles_data or not any(cycles_data.values()):
                return

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT guild_id, channel_id, message_id
                    FROM cycle_live_messages
                """)
                messages = await cur.fetchall()

            cache = get_cycle_live_embed_cache()

            for guild_id, channel_id, message_id in messages:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        await delete_cycle_live_message(guild_id, channel_id, message_id)
                        continue

                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        await delete_cycle_live_message(guild_id, channel_id, message_id)
                        continue

                    try:
                        message = await channel.fetch_message(message_id)
                    except discord.NotFound:
                        await delete_cycle_live_message(guild_id, channel_id, message_id)
                        continue

                    updated_embed = build_cycles_live_embed(bot, cycles_data)
                    fp = cycles_embed_fingerprint(updated_embed)
                    cache_key = (guild_id, channel_id, message_id)
                    if cache.get(cache_key) == fp:
                        continue

                    await safe_message_edit(message, embed=updated_embed)
                    cache[cache_key] = fp

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            """
                            UPDATE cycle_live_messages SET updated_at=?
                            WHERE guild_id=? AND channel_id=? AND message_id=?
                            """,
                            (now_utc().isoformat(), guild_id, channel_id, message_id),
                        )
                        await db.commit()

                except discord.Forbidden:
                    await delete_cycle_live_message(guild_id, channel_id, message_id)
                except Exception as e:
                    logger.error(
                        "Error updating cycle live message %s in %s: %s",
                        message_id,
                        guild_id,
                        e,
                    )
                    continue

        except Exception as e:
            logger.error(f"Error in cycle_live_update_loop: {e}", exc_info=True)

    @cycle_live_update_loop.before_loop
    async def before_cycle_live_update_loop():
        await bot.wait_until_ready()

    _WF_WARM_MINUTES = max(1, int(os.getenv("WARFRAME_CACHE_WARM_MINUTES", "1") or "1"))

    @tasks.loop(minutes=_WF_WARM_MINUTES)
    async def warframe_cache_warm_loop():
        """Keep baro/fissures/alerts cache warm so hot Warframe slash commands respond quickly."""
        try:
            if not bot.is_ready():
                return
            from api.warframe_api import warm_hot_warframe_endpoints

            await warm_hot_warframe_endpoints()
        except Exception as e:
            logger.debug("[wf-warm] cache warm failed: %s", e)

    @warframe_cache_warm_loop.before_loop
    async def before_warframe_cache_warm_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=6)  # Check every 6 hours for Warframe playtime role assignments
    async def warframe_achievement_roles_loop():
        """Assign roles based on Warframe playtime and other in-game achievements."""
        try:
            from database import (
                get_all_linked_steam_accounts,
                get_warframe_achievement_roles,
                has_warframe_achievement_unlock,
                record_warframe_achievement_unlock,
                update_steam_playtime,
            )
            from api.warframe_api import fetch_steam_warframe_playtime

            if not os.environ.get("STEAM_API_KEY"):
                return

            for guild in bot.guilds:
                try:
                    role_configs = await get_warframe_achievement_roles(guild.id)
                    if not role_configs:
                        continue

                    linked = await get_all_linked_steam_accounts(guild.id)
                    if not linked:
                        continue

                    for user_id, steam_id_64 in linked:
                        try:
                            member = guild.get_member(user_id)
                            if not member:
                                continue

                            # Fetch fresh playtime
                            hours = await fetch_steam_warframe_playtime(steam_id_64)
                            if hours is None:
                                continue
                            await update_steam_playtime(guild.id, user_id, hours)

                            # Check each playtime role config
                            for ach_type, threshold, role_id in role_configs:
                                if ach_type != "playtime":
                                    continue
                                if hours < threshold:
                                    continue
                                if await has_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold):
                                    continue

                                role = guild.get_role(role_id)
                                if not role:
                                    continue
                                if role in member.roles:
                                    await record_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold)
                                    continue
                                if not guild.me.guild_permissions.manage_roles:
                                    continue
                                if guild.me.top_role <= role:
                                    continue

                                try:
                                    await member.add_roles(role, reason=f"Warframe playtime: {hours:,}h (≥{threshold:,}h)")
                                    await record_warframe_achievement_unlock(guild.id, user_id, ach_type, threshold)
                                    logger.info(f"[warframe_roles] Assigned {role.name} to {member} ({hours}h playtime)")
                                except discord.Forbidden:
                                    logger.warning(f"[warframe_roles] Cannot assign role to {member}")
                                except Exception as e:
                                    logger.error(f"[warframe_roles] Error assigning role: {e}")
                        except Exception as e:
                            logger.error(f"[warframe_roles] Error processing user {user_id}: {e}")
                except Exception as e:
                    logger.error(f"[warframe_roles] Error processing guild {guild.id}: {e}")
        except Exception as e:
            logger.error(f"Error in warframe_achievement_roles_loop: {e}", exc_info=True)

    @warframe_achievement_roles_loop.before_loop
    async def before_warframe_achievement_roles_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)  # Check every hour for expired LFG posts
    async def lfg_expire_loop():
        """Auto-expire LFG posts that have passed their expiry time."""
        try:
            from tasks.lfg_loops import run_lfg_expire_cycle

            await run_lfg_expire_cycle(bot)
        except Exception as e:
            logger.error(f"Error in lfg_expire_loop: {e}", exc_info=True)

    @lfg_expire_loop.before_loop
    async def before_lfg_expire_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def lfg_scheduled_reminder_loop():
        """DM creators ~15 minutes before scheduled LFG start time."""
        try:
            from tasks.lfg_loops import run_lfg_scheduled_reminder_cycle

            await run_lfg_scheduled_reminder_cycle(bot)
        except Exception as e:
            logger.error(f"Error in lfg_scheduled_reminder_loop: {e}", exc_info=True)

    @lfg_scheduled_reminder_loop.before_loop
    async def before_lfg_scheduled_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def trading_expire_loop():
        """Expire stale trading posts and DM owners to renew."""
        try:
            from tasks.trading_loops import run_trading_expire_cycle

            await run_trading_expire_cycle(bot)
        except Exception as e:
            logger.error(f"Error in trading_expire_loop: {e}", exc_info=True)

    @trading_expire_loop.before_loop
    async def before_trading_expire_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=6)  # Check every 6 hours for pet decay
    async def pet_decay_reminder_loop():
        """DM users when their pet's hunger or happiness is low."""
        try:
            from tasks.economy_loops import run_pet_decay_reminder_cycle

            await run_pet_decay_reminder_cycle(bot)
        except Exception as e:
            logger.error(f"Error in pet_decay_reminder_loop: {e}", exc_info=True)

    @pet_decay_reminder_loop.before_loop
    async def before_pet_decay_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def daily_streak_reminder_loop():
        """DM opted-in users ~1 hour before their daily streak resets (23h after last claim)."""
        try:
            if not bot.is_ready():
                return

            now = now_utc()
            # Find users whose last_claim_date is today (UTC) so their reset is at next midnight
            # We want to remind them when there is between 60 and 90 minutes left until midnight UTC
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            minutes_until_midnight = (next_midnight - now).total_seconds() / 60

            if not (60 <= minutes_until_midnight <= 90):
                return  # Only fire in the 60-90 min window before midnight UTC

            today_str = now.date().isoformat()
            # At-risk users claimed YESTERDAY but not yet today: their streak resets
            # at tonight's midnight UTC unless they claim again today. (Users who
            # already claimed today are safe and must NOT be pinged.)
            yesterday_str = (now.date() - timedelta(days=1)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT guild_id, user_id, streak_days
                    FROM daily_claims
                    WHERE last_claim_date = ? AND streak_days >= 1
                """, (yesterday_str,))
                claimants = await cur.fetchall()

            for guild_id, user_id, streak_days in claimants:
                try:
                    # Check opt-in
                    opted_in = await get_guild_setting(guild_id, f"user_daily_reminder:{user_id}")
                    if opted_in != "1":
                        continue

                    # Throttle: max one reminder per day
                    last_sent = await get_guild_setting(guild_id, f"daily_reminder_sent:{user_id}")
                    if last_sent == today_str:
                        continue

                    # Respect user quiet hours (bot-initiated nudge)
                    from core.quiet_hours import in_quiet_hours
                    if await in_quiet_hours(guild_id, user_id):
                        continue

                    user = bot.get_user(user_id)
                    if not user:
                        try:
                            user = await bot.fetch_user(user_id)
                        except Exception:
                            continue

                    from commands.economy.daily import _streak_emblem
                    from core.command_mentions import command_mention

                    streak_fire = _streak_emblem(streak_days)
                    reset_ts = int(next_midnight.timestamp())
                    daily_cmd = command_mention("daily", fallback="`/daily`")
                    embed = obsidian_embed(
                        "⏰ Daily Streak Reminder",
                        f"Your **{streak_days}-day streak** resets <t:{reset_ts}:R>!\n\n"
                        f"{streak_fire}\n\nRun {daily_cmd} to keep it going.",
                        color=discord.Color.orange(),
                        footer="Turn this off with /general preferences daily_reminder:Off",
                        client=bot,
                    )
                    try:
                        await safe_dm(user,embed=embed)
                        await set_guild_setting(guild_id, f"daily_reminder_sent:{user_id}", today_str)
                    except discord.Forbidden:
                        pass
                except Exception as e:
                    logger.debug(f"daily_streak_reminder for {user_id}: {e}")

        except Exception as e:
            logger.error(f"Error in daily_streak_reminder_loop: {e}", exc_info=True)

    @daily_streak_reminder_loop.before_loop
    async def before_daily_streak_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def investment_maturity_dm_loop():
        """DM opted-in users when their investment has matured (Item 6).

        Uses a tiny guard table ``investment_dm_sent(investment_id PRIMARY KEY)``
        so we never DM the same investment twice — much safer than a schema
        migration on the existing ``investments`` table.
        """
        try:
            if not bot.is_ready():
                return

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "CREATE TABLE IF NOT EXISTS investment_dm_sent (investment_id INTEGER PRIMARY KEY, sent_at TEXT)"
                )
                await db.commit()

                cur = await db.execute(
                    """
                    SELECT i.id, i.guild_id, i.user_id, i.amount, i.interest_rate, i.maturity_date
                    FROM investments i
                    LEFT JOIN investment_dm_sent s ON s.investment_id = i.id
                    WHERE i.collected = 0
                      AND s.investment_id IS NULL
                      AND datetime(i.maturity_date) <= datetime('now')
                    LIMIT 200
                    """
                )
                rows = await cur.fetchall()

            for inv_id, guild_id, user_id, amount, rate, maturity_iso in rows:
                try:
                    opted_in = await get_guild_setting(guild_id, f"user_investment_dm:{user_id}")
                    if opted_in != "1":
                        # Still record so we don't keep scanning forever — but
                        # only when the user is not opted in. We use a separate
                        # marker row by inserting with sent_at=None? Simpler:
                        # just skip; the row remains, but it's a cheap query.
                        continue

                    from core.quiet_hours import in_quiet_hours
                    if await in_quiet_hours(guild_id, user_id):
                        continue

                    user = bot.get_user(user_id)
                    if not user:
                        try:
                            user = await bot.fetch_user(user_id)
                        except Exception:
                            continue

                    payout = int((amount or 0) * (1 + (rate or 0.0)))
                    profit = payout - (amount or 0)
                    try:
                        mat_dt = dateparser.parse(
                            maturity_iso, settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True}
                        )
                    except Exception:
                        mat_dt = None
                    when = (
                        f"<t:{int(mat_dt.timestamp())}:R>" if mat_dt else "just now"
                    )

                    embed = obsidian_embed(
                        "📈 Investment Matured!",
                        f"Your investment matured {when}.\n\n"
                        f"Use **`/economy invest_collect`** to claim your payout.",
                        category="economy",
                        fields=[
                            ("💰 Principal", f"{(amount or 0):,} coins", True),
                            ("💎 Payout", f"{payout:,} coins", True),
                            ("✨ Profit", f"+{profit:,} coins", True),
                        ],
                        footer="Turn this off with /general preferences investment_dm:Off",
                        client=bot,
                    )

                    try:
                        await safe_dm(user,embed=embed)
                    except discord.Forbidden:
                        # Mark sent anyway — user can re-open DMs and check
                        # via /economy invest_status; we don't want to retry
                        # forever and rate-limit ourselves.
                        pass
                    except Exception as e:
                        logger.debug(f"investment_maturity_dm: failed to DM {user_id}: {e}")
                        continue

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "INSERT OR IGNORE INTO investment_dm_sent (investment_id, sent_at) VALUES (?, ?)",
                            (inv_id, now_utc().isoformat()),
                        )
                        await db.commit()
                except Exception as e:
                    logger.debug(f"investment_maturity_dm for {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error in investment_maturity_dm_loop: {e}", exc_info=True)

    @investment_maturity_dm_loop.before_loop
    async def before_investment_maturity_dm_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)  # Check every 5 minutes for cycle changes
    async def cycle_check_loop():
        """Check for cycle changes and send notifications."""
        try:
            # Verify bot is ready
            if not bot.is_ready():
                return
            from tasks.wf_check_loops import run_cycle_change_notifications

            await run_cycle_change_notifications(bot, _warn_broken_channel)
        except Exception as e:
            logger.error(f"Error in cycle_check_loop: {e}", exc_info=True)

    @cycle_check_loop.before_loop
    async def before_cycle_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=10)  # Check every 10 minutes for new invasions
    async def invasion_check_loop():
        """Check for new invasions and send notifications for configured rewards."""
        try:
            # Verify bot is ready
            if not bot.is_ready():
                return
            from tasks.wf_check_loops import run_invasion_notifications

            await run_invasion_notifications(bot, _warn_broken_channel)
        except Exception as e:
            logger.error(f"Error in invasion_check_loop: {e}", exc_info=True)

    @invasion_check_loop.before_loop
    async def before_invasion_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)  # Check every hour for archon hunt resets
    async def archon_check_loop():
        """Check for new Archon Hunts and send notifications."""
        try:
            from tasks.wf_check_loops import run_archon_notifications

            await run_archon_notifications(bot, _warn_broken_channel)
        except Exception as e:
            logger.error(f"Error in archon_check_loop: {e}", exc_info=True)

    @archon_check_loop.before_loop
    async def before_archon_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)  # Check every minute for ended giveaways
    async def giveaway_check_loop():
        """Check for ended giveaways and select winners."""
        try:
            from tasks.giveaway_loops import check_ended_giveaways

            await check_ended_giveaways(bot)
        except Exception as e:
            logger.error(f"[giveaway] Error in giveaway check loop: {e}", exc_info=True)
    
    async def before_giveaway_check_loop():
        await bot.wait_until_ready()
    
    giveaway_check_loop.before_loop(before_giveaway_check_loop)
    giveaway_check_loop.start()
    logger.info("[tasks] Started giveaway check loop")
    
    @tasks.loop(minutes=2)  # Update every 2 minutes for accuracy
    async def member_count_update_loop():
        """Update member count channel names with accurate counts."""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT guild_id, channel_id FROM member_count_channels"
                )
                channels = await cur.fetchall()
            
            for guild_id, channel_id in channels:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                # Update member count channel
                try:
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        # Channel was deleted, remove from database
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "DELETE FROM member_count_channels WHERE guild_id=? AND channel_id=?",
                                (guild_id, channel_id)
                            )
                            await db.commit()
                        continue
                    
                    # Get accurate member count
                    # guild.member_count is usually accurate, but we can verify by counting
                    member_count = guild.member_count
                    
                    # Count bots and humans from cached members
                    # Note: For very large servers, not all members may be cached
                    # But guild.member_count should be accurate regardless
                    bot_count = sum(1 for member in guild.members if member.bot)
                    
                    # If we have all members cached, use the cached count
                    # Otherwise, estimate based on cached ratio
                    if len(guild.members) == member_count:
                        # All members cached, accurate count
                        human_count = member_count - bot_count
                    else:
                        # Not all members cached, estimate based on ratio
                        if len(guild.members) > 0:
                            bot_ratio = bot_count / len(guild.members)
                            human_count = int(member_count * (1 - bot_ratio))
                        else:
                            # Fallback: assume 5% bots (typical Discord server)
                            human_count = int(member_count * 0.95)
                            bot_count = member_count - human_count
                    
                    # Format channel name using the same refined format
                    from commands.general.member_count import format_member_count_name
                    name = format_member_count_name(member_count, bot_count, human_count)
                    
                    # Only update if name changed (to avoid rate limits)
                    if channel.name != name:
                        await channel.edit(name=name, reason="Member count update")
                        logger.debug(f"Updated member count channel {channel_id} in guild {guild_id}: {name}")
                except discord.Forbidden:
                    logger.warning(f"No permission to update member count channel {channel_id} in guild {guild_id}")
                except Exception as e:
                    logger.error(f"Error updating member count channel {channel_id} in {guild.id}: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error in member_count_update_loop: {e}", exc_info=True)

    @member_count_update_loop.before_loop
    async def before_member_count_update_loop():
        await bot.wait_until_ready()
    
    @tasks.loop(minutes=5)  # Update every 5 minutes
    async def server_stats_update_loop():
        """Update server stats channel names."""
        from database import get_server_stats_channel
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT guild_id FROM server_stats_channels WHERE enabled = 1
                """)
                guilds = await cur.fetchall()
            
            for (guild_id,) in guilds:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                settings = await get_server_stats_channel(guild_id)
                if not settings or not settings["enabled"]:
                    continue
                
                channel = guild.get_channel(settings["channel_id"])
                if not channel:
                    # Channel was deleted, disable stats
                    from database import remove_server_stats_channel
                    await remove_server_stats_channel(guild_id)
                    continue
                
                try:
                    stats_type = settings["stats_type"]
                    new_name = None
                    
                    if stats_type == "members":
                        member_count = guild.member_count
                        bot_count = sum(1 for m in guild.members if m.bot)
                        human_count = member_count - bot_count
                        new_name = f"👥 {member_count:,} Members • 🤖 {bot_count:,} Bots • 👤 {human_count:,} Humans"
                    
                    elif stats_type == "boosts":
                        boost_count = guild.premium_subscription_count or 0
                        boost_level = guild.premium_tier
                        new_name = f"🚀 {boost_count} Boosts • Level {boost_level}"
                    
                    elif stats_type == "channels":
                        text_channels = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
                        voice_channels = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
                        total_channels = len(guild.channels)
                        new_name = f"💬 {text_channels} Text • 🔊 {voice_channels} Voice • 📊 {total_channels} Total"
                    
                    elif stats_type == "roles":
                        role_count = len(guild.roles)
                        new_name = f"🎭 {role_count} Roles"
                    
                    if new_name and channel.name != new_name:
                        # Discord channel name limit is 100 characters
                        if len(new_name) > 100:
                            new_name = new_name[:97] + "..."
                        await channel.edit(name=new_name)
                        logger.info(f"Updated server stats for guild {guild_id}: {new_name}")
                
                except discord.Forbidden:
                    logger.warning(f"No permission to edit stats channel in guild {guild_id}")
                except Exception as e:
                    logger.error(f"Error updating server stats for guild {guild_id}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in server_stats_update_loop: {e}", exc_info=True)
    
    @server_stats_update_loop.before_loop
    async def before_server_stats_update_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)  # Check every 5 minutes for new alerts
    async def alert_check_loop():
        """Check for new Warframe alerts and send notifications."""
        try:
            if not bot.is_ready():
                return
            from tasks.wf_check_loops import run_alert_notifications

            await run_alert_notifications(bot)
        except Exception as e:
            logger.error(f"Error in alert_check_loop: {e}", exc_info=True)
    
    @alert_check_loop.before_loop
    async def before_alert_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)  # Check every hour for upcoming devstreams
    async def devstream_check_loop():
        """Check for upcoming devstreams and send notifications. Also auto-detect and set devstream dates."""
        try:
            from tasks.wf_feed_loops import run_devstream_notify_cycle

            await run_devstream_notify_cycle(bot)
        except Exception as e:
            logger.error(f"Error in devstream_check_loop: {e}", exc_info=True)
    
    @devstream_check_loop.before_loop
    async def before_devstream_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)  # Check every minute for reminders
    async def reminder_check_loop():
        """Check for due reminders and send them."""
        try:
            from tasks.community_loops import run_reminder_check_cycle

            await run_reminder_check_cycle(bot)
        except Exception as e:
            logger.error(f"Error in reminder_check_loop: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in reminder_check_loop: {e}", exc_info=True)
    
    @reminder_check_loop.before_loop
    async def before_reminder_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def poll_close_loop():
        """Close expired polls and post final results embeds (QoL #20)."""
        try:
            from tasks.community_loops import run_poll_close_cycle

            await run_poll_close_cycle(bot)
        except Exception as e:
            logger.error(f"Error in poll_close_loop: {e}", exc_info=True)

    @poll_close_loop.before_loop
    async def before_poll_close_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def scheduled_messages_loop():
        """Send scheduled messages when due."""
        try:
            from tasks.community_loops import run_scheduled_messages_cycle

            await run_scheduled_messages_cycle(bot)
        except Exception as e:
            logger.error(f"Error in scheduled_messages_loop: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[schedule] Error in scheduled_messages_loop: {e}", exc_info=True)

    @scheduled_messages_loop.before_loop
    async def before_scheduled_messages_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)  # Check every 5 minutes for Twitch streams
    async def twitch_check_loop():
        """Check for Twitch streamers going live."""
        try:
            from tasks.integration_loops import run_twitch_live_cycle

            await run_twitch_live_cycle(bot)
        except Exception as e:
            logger.error(f"Error in twitch_check_loop: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in twitch_check_loop: {e}", exc_info=True)
    
    @twitch_check_loop.before_loop
    async def before_twitch_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def stale_ticket_reminder_loop():
        """Remind staff about idle tickets; auto-close if still idle after warning."""
        try:
            from tasks.ticket_loops import run_stale_ticket_reminder_cycle

            await run_stale_ticket_reminder_cycle(bot)
        except Exception as e:
            logger.error(f"Error in stale_ticket_reminder_loop: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[stale_ticket] Error in stale_ticket_reminder_loop: {e}", exc_info=True)

    @stale_ticket_reminder_loop.before_loop
    async def before_stale_ticket_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def ticket_sla_breach_loop():
        """Ping mod channel when open tickets lack first response past SLA."""
        try:
            from tasks.ticket_loops import run_ticket_sla_breach_cycle

            await run_ticket_sla_breach_cycle(bot)
        except Exception as e:
            logger.error(f"Error in ticket_sla_breach_loop: {e}", exc_info=True)

    @ticket_sla_breach_loop.before_loop
    async def before_ticket_sla_breach_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def giveaway_ending_soon_loop():
        """DM entrants ~1 hour before a giveaway ends."""
        try:
            from tasks.giveaway_loops import run_giveaway_ending_soon_cycle

            await run_giveaway_ending_soon_cycle(bot)
        except Exception as e:
            logger.debug(f"[giveaway] ending-soon loop: {e}")

    @giveaway_ending_soon_loop.before_loop
    async def before_giveaway_ending_soon_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def forum_check_loop():
        """Check Warframe forums RSS for new posts."""
        try:
            from tasks.wf_feed_loops import run_forum_feed_cycle

            await run_forum_feed_cycle(bot)
        except Exception as e:
            logger.error(f"Error in forum_check_loop: {e}", exc_info=True)

    @forum_check_loop.before_loop
    async def before_forum_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def youtube_check_loop():
        """Check Warframe YouTube channel RSS for new videos."""
        try:
            from tasks.wf_feed_loops import run_youtube_feed_cycle

            await run_youtube_feed_cycle(bot)
        except Exception as e:
            logger.error(f"Error in youtube_check_loop: {e}", exc_info=True)

    @youtube_check_loop.before_loop
    async def before_youtube_check_loop():
        await bot.wait_until_ready()

    from tasks.digest_loop import create_digest_loop
    digest_dm_loop = create_digest_loop(bot)

    from tasks.weekly_recap_loop import create_weekly_recap_loop
    weekly_recap_loop = create_weekly_recap_loop(bot)

    from tasks.mod_kpi_digest_loop import create_mod_kpi_digest_loop
    mod_kpi_digest_loop = create_mod_kpi_digest_loop(bot)

    @tasks.loop(minutes=1)
    async def music_auto_leave_loop():
        """Disconnect from voice when the channel is empty too long."""
        try:
            if not bot.is_ready():
                return
            from core.music_player import music_auto_leave_tick

            await music_auto_leave_tick(bot)
        except Exception as e:
            logger.error(f"[music] auto-leave loop error: {e}", exc_info=True)

    @music_auto_leave_loop.before_loop
    async def before_music_auto_leave_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def price_watch_loop():
        try:
            if not bot.is_ready():
                return
            from core.price_watchlist import check_price_watches

            await check_price_watches(bot)
        except Exception as e:
            logger.error(f"[price_watch] loop error: {e}", exc_info=True)

    @price_watch_loop.before_loop
    async def before_price_watch_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def lfg_bump_loop():
        """Bump stale LFG posts with no replies after 30+ minutes."""
        try:
            from tasks.lfg_loops import run_lfg_bump_cycle

            await run_lfg_bump_cycle(bot)
        except Exception as e:
            logger.error(f"[lfg_bump] loop error: {e}", exc_info=True)

    @lfg_bump_loop.before_loop
    async def before_lfg_bump_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=20)
    async def lfg_poster_nudge_loop():
        """DM LFG creators after ~2h with no thread replies."""
        try:
            from tasks.lfg_loops import run_lfg_poster_nudge_cycle

            await run_lfg_poster_nudge_cycle(bot)
        except Exception as e:
            logger.error(f"[lfg_nudge] loop error: {e}", exc_info=True)

    @lfg_poster_nudge_loop.before_loop
    async def before_lfg_poster_nudge_loop():
        await bot.wait_until_ready()

    # Start all tasks with error handling
    tasks_to_start = [
        ('temp_vc_cleanup', temp_vc_cleanup),
        ('event_reminder_loop', event_reminder_loop),
        ('recurring_event_loop', recurring_event_loop),
        ('event_end_loop', event_end_loop),
        ('event_rsvp_reminder_loop', event_rsvp_reminder_loop),
        ('inactive_role_sweep_loop', inactive_role_sweep_loop),
        ('goal_progress_loop', goal_progress_loop),
        ('voice_reward_loop', voice_reward_loop),
        ('baro_check_loop', baro_check_loop),
        ('baro_live_update_loop', baro_live_update_loop),
        ('cycle_live_update_loop', cycle_live_update_loop),
        ('warframe_cache_warm_loop', warframe_cache_warm_loop),
        ('warframe_achievement_roles_loop', warframe_achievement_roles_loop),
        ('lfg_expire_loop', lfg_expire_loop),
        ('lfg_scheduled_reminder_loop', lfg_scheduled_reminder_loop),
        ('trading_expire_loop', trading_expire_loop),
        ('pet_decay_reminder_loop', pet_decay_reminder_loop),
        ('daily_streak_reminder_loop', daily_streak_reminder_loop),
        ('investment_maturity_dm_loop', investment_maturity_dm_loop),
        ('cycle_check_loop', cycle_check_loop),
        ('invasion_check_loop', invasion_check_loop),
        ('archon_check_loop', archon_check_loop),
        ('member_count_update_loop', member_count_update_loop),
        ('server_stats_update_loop', server_stats_update_loop),
        ('alert_check_loop', alert_check_loop),
        ('devstream_check_loop', devstream_check_loop),
        ('reminder_check_loop', reminder_check_loop),
        ('poll_close_loop', poll_close_loop),
        ('scheduled_messages_loop', scheduled_messages_loop),
        ('twitch_check_loop', twitch_check_loop),
        ('stale_ticket_reminder_loop', stale_ticket_reminder_loop),
        ('ticket_sla_breach_loop', ticket_sla_breach_loop),
        ('giveaway_ending_soon_loop', giveaway_ending_soon_loop),
        ('forum_check_loop', forum_check_loop),
        ('youtube_check_loop', youtube_check_loop),
        ('digest_dm_loop', digest_dm_loop),
        ('price_watch_loop', price_watch_loop),
        ('lfg_bump_loop', lfg_bump_loop),
        ('lfg_poster_nudge_loop', lfg_poster_nudge_loop),
        ('weekly_recap_loop', weekly_recap_loop),
        ('mod_kpi_digest_loop', mod_kpi_digest_loop),
        ('music_auto_leave_loop', music_auto_leave_loop),
    ]
    
    started_tasks = {}
    for task_name, task in tasks_to_start:
        try:
            # Restart task if it's already running (handles bot restarts)
            if task.is_running():
                task.restart()
                logger.info(f"[tasks] Restarted {task_name}")
            else:
                task.start()
                logger.info(f"[tasks] Started {task_name}")
            started_tasks[task_name] = task
        except Exception as e:
            logger.error(f"[tasks] Failed to start {task_name}: {e}", exc_info=True)
            # Try to start it anyway
            try:
                task.start()
                started_tasks[task_name] = task
                logger.info(f"[tasks] Successfully started {task_name} on retry")
            except Exception as e2:
                logger.error(f"[tasks] Failed to start {task_name} on retry: {e2}")
    
    logger.info(f"[tasks] Started {len(started_tasks)}/{len(tasks_to_start)} background tasks")

    bot._background_tasks = started_tasks

    return started_tasks
