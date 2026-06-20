"""
Background task loop registry.

All @tasks.loop closures and the tasks_to_start registry live here.
Import via ``from tasks import setup_tasks`` (re-exported from tasks/_core.py).
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
        try:
            from tasks.vc_loops import run_temp_vc_cleanup_cycle

            await run_temp_vc_cleanup_cycle(bot)
        except Exception as e:
            logger.error(f"Error in temp_vc_cleanup: {e}", exc_info=True)

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
            from tasks.moderation_loops import run_inactive_role_sweep_cycle

            await run_inactive_role_sweep_cycle(bot)
        except Exception as e:
            logger.error(f"Error in inactive_role_sweep_loop: {e}", exc_info=True)

    @inactive_role_sweep_loop.before_loop
    async def before_inactive_role_sweep_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def goal_progress_loop():
        """Item 72 — recompute server-wide goal progress every 15 minutes."""
        try:
            from tasks.moderation_loops import run_goal_progress_cycle

            await run_goal_progress_cycle(bot)
        except Exception as e:
            logger.error(f"Error in goal_progress_loop: {e}", exc_info=True)

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
            from tasks.wf_live_loops import run_baro_live_update_cycle

            await run_baro_live_update_cycle(bot)
        except Exception as e:
            logger.error(f"Error in baro_live_update_loop: {e}", exc_info=True)

    @baro_live_update_loop.before_loop
    async def before_baro_live_update_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=CYCLE_LIVE_UPDATE_MINUTES)
    async def cycle_live_update_loop():
        """Update pinned live cycle panels in place."""
        try:
            from tasks.wf_live_loops import run_cycle_live_update_cycle

            await run_cycle_live_update_cycle(bot)
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
            from tasks.wf_live_loops import run_warframe_cache_warm_cycle

            await run_warframe_cache_warm_cycle(bot)
        except Exception as e:
            logger.debug("[wf-warm] cache warm failed: %s", e)

    @warframe_cache_warm_loop.before_loop
    async def before_warframe_cache_warm_loop():
        await bot.wait_until_ready()
        try:
            from tasks.wf_live_loops import run_warframe_cache_warm_cycle

            await run_warframe_cache_warm_cycle(bot)
            logger.info("[wf-warm] initial Warframe cache warm complete")
        except Exception as e:
            logger.debug("[wf-warm] initial cache warm failed: %s", e)

    @tasks.loop(hours=6)  # Check every 6 hours for Warframe playtime role assignments
    async def warframe_achievement_roles_loop():
        """Assign roles based on Warframe playtime and other in-game achievements."""
        try:
            from tasks.wf_roles_loops import run_warframe_achievement_roles_cycle

            await run_warframe_achievement_roles_cycle(bot)
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
            from tasks.economy_loops import run_daily_streak_reminder_cycle

            await run_daily_streak_reminder_cycle(bot)
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
            from tasks.economy_loops import run_investment_maturity_dm_cycle

            await run_investment_maturity_dm_cycle(bot)
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

    @giveaway_check_loop.before_loop
    async def before_giveaway_check_loop():
        await bot.wait_until_ready()

    
    @tasks.loop(minutes=2)  # Update every 2 minutes for accuracy
    async def member_count_update_loop():
        """Update member count channel names with accurate counts."""
        try:
            from tasks.guild_stats_loops import run_member_count_update_cycle

            await run_member_count_update_cycle(bot)
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
            from tasks.guild_stats_loops import run_server_stats_update_cycle

            await run_server_stats_update_cycle(bot)
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

    @scheduled_messages_loop.before_loop
    async def before_scheduled_messages_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=3)  # Check every 3 minutes for Twitch streams
    async def twitch_check_loop():
        """Check for Twitch streamers going live."""
        try:
            from tasks.integration_loops import run_twitch_live_cycle

            await run_twitch_live_cycle(bot)
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

    @tasks.loop(minutes=2)
    async def dm_coalesce_flush_loop():
        try:
            from core.dm_coalesce import flush_all_coalesced_dms

            await flush_all_coalesced_dms(bot)
        except Exception as e:
            logger.error(f"Error in dm_coalesce_flush_loop: {e}", exc_info=True)

    @dm_coalesce_flush_loop.before_loop
    async def before_dm_coalesce_flush_loop():
        await bot.wait_until_ready()

    from tasks.mod_kpi_digest_loop import create_mod_kpi_digest_loop
    mod_kpi_digest_loop = create_mod_kpi_digest_loop(bot)

    @tasks.loop(minutes=1)
    async def music_auto_leave_loop():
        """Disconnect from voice when the channel is empty too long."""
        try:
            from tasks.misc_loops import run_music_auto_leave_cycle

            await run_music_auto_leave_cycle(bot)
        except Exception as e:
            logger.error(f"Error in music_auto_leave_loop: {e}", exc_info=True)

    @music_auto_leave_loop.before_loop
    async def before_music_auto_leave_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def price_watch_loop():
        try:
            from tasks.misc_loops import run_price_watch_cycle

            await run_price_watch_cycle(bot)
        except Exception as e:
            logger.error(f"Error in price_watch_loop: {e}", exc_info=True)

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

    @tasks.loop(hours=6)
    async def member_journey_loop():
        """Day 1/3/7 new-member DM nudges."""
        try:
            from core.member_journey import run_member_journey_cycle

            await run_member_journey_cycle(bot)
        except Exception as e:
            logger.error(f"[member_journey] loop error: {e}", exc_info=True)

    @member_journey_loop.before_loop
    async def before_member_journey_loop():
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
        ('giveaway_check_loop', giveaway_check_loop),
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
        ('member_journey_loop', member_journey_loop),
        ('weekly_recap_loop', weekly_recap_loop),
        ('dm_coalesce_flush_loop', dm_coalesce_flush_loop),
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
