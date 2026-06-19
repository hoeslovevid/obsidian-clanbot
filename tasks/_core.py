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
            now = now_utc()
            window_start = int((now + timedelta(minutes=30)).timestamp())
            window_end = int((now + timedelta(minutes=35)).timestamp())

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS event_dm_reminders_sent (
                        event_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        sent_at TEXT NOT NULL,
                        PRIMARY KEY (event_id, user_id)
                    )
                    """
                )
                await db.commit()

            from core.utils import feature_enabled  # Item 85 — kill switch
            for guild in bot.guilds:
                guild_toggle = await get_guild_setting(guild.id, "event_rsvp_dm_reminders_enabled")
                if guild_toggle == "0":
                    continue
                if not await feature_enabled(guild.id, "notifications"):
                    continue
                if not await feature_enabled(guild.id, "events"):
                    continue

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        """
                        SELECT message_id, title, start_ts
                        FROM events
                        WHERE guild_id=? AND ended=0 AND start_ts BETWEEN ? AND ?
                        """,
                        (guild.id, window_start, window_end),
                    )
                    upcoming = await cur.fetchall()

                events_id = await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
                events_channel = guild.get_channel(events_id) if events_id else None

                for message_id, title, start_ts in upcoming:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT user_id FROM event_rsvps WHERE guild_id=? AND message_id=? AND response='GOING'",
                            (guild.id, int(message_id)),
                        )
                        going_users = [int(r[0]) for r in await cur.fetchall()]

                    if not going_users:
                        continue

                    jump_url = None
                    if isinstance(events_channel, discord.TextChannel):
                        jump_url = f"https://discord.com/channels/{guild.id}/{events_channel.id}/{int(message_id)}"

                    for user_id in going_users:
                        async with aiosqlite.connect(DB_PATH) as db:
                            cur = await db.execute(
                                "SELECT 1 FROM event_dm_reminders_sent WHERE event_id=? AND user_id=?",
                                (int(message_id), user_id),
                            )
                            if await cur.fetchone():
                                continue

                        opt = await get_guild_setting(guild.id, f"user_event_dm:{user_id}")
                        if opt == "0":
                            continue

                        member = guild.get_member(user_id)
                        if not member or member.bot:
                            continue

                        embed = obsidian_embed(
                            "⏰ Event Reminder",
                            f"**{title}** in **{guild.name}** starts <t:{int(start_ts)}:R> (<t:{int(start_ts)}:F>).",
                            color=discord.Color.orange(),
                            client=bot,
                            footer="You can opt out via /general preferences.",
                        )
                        if events_channel:
                            embed.add_field(
                                name="Location",
                                value=f"<#{events_channel.id}>",
                                inline=False,
                            )

                        view = None
                        if jump_url:
                            view = discord.ui.View(timeout=None)
                            view.add_item(discord.ui.Button(label="View Event", style=discord.ButtonStyle.link, url=jump_url))

                        try:
                            if view is not None:
                                await safe_dm(member,embed=embed, view=view)
                            else:
                                await safe_dm(member,embed=embed)
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute(
                                    "INSERT OR IGNORE INTO event_dm_reminders_sent (event_id, user_id, sent_at) VALUES (?, ?, ?)",
                                    (int(message_id), user_id, now.isoformat()),
                                )
                                await db.commit()
                        except (discord.Forbidden, discord.HTTPException):
                            # Still mark as sent so we don't keep retrying every 5 min
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute(
                                    "INSERT OR IGNORE INTO event_dm_reminders_sent (event_id, user_id, sent_at) VALUES (?, ?, ?)",
                                    (int(message_id), user_id, now.isoformat()),
                                )
                                await db.commit()
        except Exception as e:
            logger.error(f"[events] Error in event_rsvp_reminder_loop: {e}", exc_info=True)

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
            async with aiosqlite.connect(DB_PATH) as db:
                now = datetime.now(timezone.utc).isoformat()
                
                # Find expired posts
                cur = await db.execute("""
                    SELECT id, guild_id, channel_id, message_id, thread_id
                    FROM lfg_posts
                    WHERE status='OPEN' AND expires_at < ?
                """, (now,))
                
                expired = await cur.fetchall()
                
                for lfg_id, guild_id, channel_id, message_id, thread_id in expired:
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

                        try:
                            from core.lfg_extras import post_lfg_thread_summary
                            await post_lfg_thread_summary(
                                bot, guild_id, lfg_id, thread_id, reason="expired",
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"Error expiring LFG post {lfg_id}: {e}", exc_info=True)
                        continue
        except Exception as e:
            logger.error(f"Error in lfg_expire_loop: {e}", exc_info=True)

    @lfg_expire_loop.before_loop
    async def before_lfg_expire_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def lfg_scheduled_reminder_loop():
        """DM creators ~15 minutes before scheduled LFG start time."""
        try:
            import dateparser
            from core.embed_templates import embed_template
            from core.embed_footers import footer_for
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, guild_id, creator_id, mission_type, scheduled_at
                    FROM lfg_posts
                    WHERE status='OPEN' AND scheduled_at IS NOT NULL AND scheduled_at != ''
                      AND COALESCE(reminder_sent, 0) = 0
                """)
                rows = await cur.fetchall()
            now = now_utc()
            for lfg_id, guild_id, creator_id, mission, sched_raw in rows:
                try:
                    sched_dt = dateparser.parse(
                        sched_raw,
                        settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
                    )
                    if not sched_dt:
                        continue
                    if sched_dt.tzinfo is None:
                        sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                    delta = (sched_dt - now).total_seconds()
                    if not (0 < delta <= 15 * 60):
                        continue
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    member = guild.get_member(creator_id)
                    if member:
                        await safe_dm(member,
                            embed=embed_template(
                                "showcase",
                                "⏰ LFG starting soon",
                                f"Your **{mission}** squad is scheduled for <t:{int(sched_dt.timestamp())}:R>.\n"
                                f"Head to your LFG post to rally your squad.",
                                category="community",
                                footer=footer_for("community_lfg"),
                                client=bot,
                            ),
                        )
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE lfg_posts SET reminder_sent=1 WHERE id=?",
                            (lfg_id,),
                        )
                        await db.commit()
                except Exception as e:
                    logger.debug("[lfg_reminder] %s: %s", lfg_id, e)
        except Exception as e:
            logger.error(f"Error in lfg_scheduled_reminder_loop: {e}", exc_info=True)

    @lfg_scheduled_reminder_loop.before_loop
    async def before_lfg_scheduled_reminder_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def trading_expire_loop():
        """Expire stale trading posts and DM owners to renew."""
        try:
            from core.utils import obsidian_embed
            from database import get_guild_setting, set_guild_setting
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            soon = (now_dt + timedelta(hours=24)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT id, guild_id, user_id, item_name, listing_type
                    FROM trading_posts
                    WHERE status='ACTIVE' AND expires_at IS NOT NULL
                      AND expires_at > ? AND expires_at <= ?
                    """,
                    (now, soon),
                )
                expiring_soon = await cur.fetchall()
                for listing_id, guild_id, user_id, item_name, listing_type in expiring_soon:
                    if await get_guild_setting(guild_id, f"trade_expiry_warned:{listing_id}"):
                        continue
                    guild = bot.get_guild(int(guild_id))
                    member = guild.get_member(int(user_id)) if guild else None
                    if member:
                        try:
                            from core.quiet_hours import in_quiet_hours
                            if not await in_quiet_hours(guild_id, user_id):
                                await safe_dm(member,
                                    embed=obsidian_embed(
                                        "⏰ Listing expires soon",
                                        f"Your **{listing_type}** for **{item_name}** expires within 24 hours.\n\n"
                                        "Repost with `/trading trade` when it expires.",
                                        color=discord.Color.orange(),
                                        client=bot,
                                    )
                                )
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    await set_guild_setting(guild_id, f"trade_expiry_warned:{listing_id}", "1")

                cur = await db.execute("""
                    SELECT id, guild_id, user_id, item_name, listing_type, message_id, channel_id
                    FROM trading_posts
                    WHERE status='ACTIVE' AND expires_at IS NOT NULL AND expires_at < ?
                """, (now,))
                expired = await cur.fetchall()

                for listing_id, guild_id, user_id, item_name, listing_type, message_id, channel_id in expired:
                    try:
                        guild = bot.get_guild(guild_id)
                        if guild and message_id and channel_id:
                            channel = guild.get_channel(int(channel_id))
                            if isinstance(channel, discord.TextChannel):
                                try:
                                    msg = await channel.fetch_message(int(message_id))
                                    if msg.embeds:
                                        embed = msg.embeds[0]
                                        embed.color = discord.Color.greyple()
                                        embed.set_footer(text="⏰ Listing expired — repost with /trading trade")
                                        await msg.edit(embed=embed, view=None)
                                except discord.NotFound:
                                    pass
                                except discord.HTTPException:
                                    pass

                        member = guild.get_member(int(user_id)) if guild else None
                        if member:
                            try:
                                dm = obsidian_embed(
                                    "⏰ Trading Listing Expired",
                                    f"Your **{listing_type}** listing for **{item_name}** expired after 14 days.\n\n"
                                    f"Run **`/trading trade`** in **{guild.name if guild else 'the server'}** "
                                    f"to post a fresh listing.",
                                    color=discord.Color.orange(),
                                    client=bot,
                                )
                                await safe_dm(member,embed=dm)
                            except (discord.Forbidden, discord.HTTPException):
                                pass

                        await db.execute(
                            "UPDATE trading_posts SET status='EXPIRED', updated_at=? WHERE id=?",
                            (now, listing_id),
                        )
                        await db.commit()
                    except Exception as e:
                        logger.error(f"Error expiring trading post {listing_id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error in trading_expire_loop: {e}", exc_info=True)

    @trading_expire_loop.before_loop
    async def before_trading_expire_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=6)  # Check every 6 hours for pet decay
    async def pet_decay_reminder_loop():
        """DM users when their pet's hunger or happiness is low."""
        try:
            if not bot.is_ready() or not ECONOMY_ENABLED:
                return
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT guild_id, user_id, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at
                    FROM pets
                """)
                pets = await cur.fetchall()

            now = now_utc()
            for guild_id, user_id, pet_name, hunger, happiness, last_fed, last_played, created_at in pets:
                try:
                    h = _apply_decay(hunger, last_fed, created_at, HUNGER_DECAY_PER_HOUR)
                    hap = _apply_decay(happiness, last_played, created_at, HAPPINESS_DECAY_PER_HOUR)
                    if h >= 50 and hap >= 50:
                        continue

                    # Check last reminder (max 1 per 12 hours)
                    last_key = f"pet_decay_reminder_{user_id}"
                    last_reminder = await get_guild_setting(guild_id, last_key)
                    if last_reminder:
                        try:
                            last_dt = datetime.fromisoformat(last_reminder.replace("Z", "+00:00"))
                            if (now - last_dt.replace(tzinfo=timezone.utc)).total_seconds() < 12 * 3600:
                                continue
                        except Exception:
                            pass

                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    user = guild.get_member(user_id)
                    if not user:
                        try:
                            user = await bot.fetch_user(user_id)
                        except Exception:
                            continue

                    issues = []
                    if h < 50:
                        issues.append(f"hunger ({h}/100)")
                    if hap < 50:
                        issues.append(f"happiness ({hap}/100)")

                    msg = f"Your pet **{pet_name}** needs attention! Low: {', '.join(issues)}.\n\nUse `/economy pet_feed` and `/economy pet_play` to care for your pet."
                    try:
                        await safe_dm(user,embed=obsidian_embed("🐾 Pet Needs Care", msg, color=discord.Color.orange(), client=bot))
                        await set_guild_setting(guild_id, last_key, now.isoformat())
                    except discord.Forbidden:
                        pass
                except Exception as e:
                    logger.debug(f"Pet decay reminder for user {user_id}: {e}")

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
            # Verify bot is ready
            if not bot.is_ready():
                return
            archon_data = await fetch_archon_hunt_data()
            
            if not archon_data:
                return
            
            boss = archon_data.get("boss", "Unknown")
            expiry = archon_data.get("expiry", "")
            
            if not boss or not expiry:
                return
            
            # Map archon names to shard types
            archon_shards = {
                "Amar": "Crimson Archon Shard",
                "Nira": "Amber Archon Shard",
                "Boreal": "Azure Archon Shard"
            }
            
            shard_type = archon_shards.get(boss, "Unknown Shard")
            faction = archon_data.get("faction", "Unknown")
            missions = archon_data.get("missions", [])
            
            # Parse expiry time
            try:
                expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                if not expiry_time:
                    return
            except Exception:
                return
            
            # Send notifications to all guilds that have it enabled
            for guild in bot.guilds:
                try:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT channel_id, enabled FROM archon_notification_settings WHERE guild_id=?",
                            (guild.id,)
                        )
                        setting = await cur.fetchone()
                    
                    if not setting or not setting[1]:  # Not enabled or not set
                        continue
                except Exception as e:
                    logger.error(f"Error checking archon notification settings for guild {guild.id}: {e}")
                    continue
                
                channel_id = setting[0]
                if not channel_id:
                    continue
                
                ch = guild.get_channel(channel_id)
                if not isinstance(ch, discord.TextChannel):
                    await _warn_broken_channel(guild, channel_id, "Archon Hunt")
                    continue
                
                # Check if we've already notified this guild for this hunt
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute("""
                        SELECT 1 FROM archon_notifications_sent
                        WHERE guild_id=? AND archon_boss=? AND expiry_time=?
                    """, (guild.id, boss, expiry))
                    already_notified = await cur.fetchone()
                
                if already_notified:
                    continue
                
                # Build notification embed
                time_remaining = expiry_time - datetime.now(timezone.utc)
                total_seconds = int(time_remaining.total_seconds())
                days = total_seconds // 86400
                hours = (total_seconds % 86400) // 3600
                minutes = (total_seconds % 3600) // 60
                
                if days > 0:
                    time_str = f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    time_str = f"{hours}h {minutes}m"
                else:
                    time_str = f"{minutes}m"
                
                desc = f"**Archon:** {boss}\n"
                desc += f"**Reward:** {shard_type}\n"
                desc += f"**Faction:** {faction}\n"
                desc += f"**Time Remaining:** {time_str}\n"
                desc += f"**Expires:** <t:{int(expiry_time.timestamp())}:R>\n\n"
                
                # Add mission information
                if missions:
                    desc += "**Missions:**\n"
                    for i, mission in enumerate(missions, 1):
                        node = mission.get("node", "Unknown")
                        mission_type = mission.get("type", "Unknown")
                        desc += f"{i}. {node} - {mission_type}\n"
                
                # Determine color based on archon
                color_map = {
                    "Amar": discord.Color.red(),
                    "Nira": discord.Color.gold(),
                    "Boreal": discord.Color.blue()
                }
                color = color_map.get(boss, discord.Color.purple())
                
                embed = obsidian_embed(
                    "⚔️ New Archon Hunt Available!",
                    desc,
                    color=color,
                    client=bot,
                )
                
                try:
                    await ch.send(embed=embed)
                    
                    # Record notification
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("""
                            INSERT INTO archon_notifications_sent (guild_id, archon_boss, expiry_time, notified_at)
                            VALUES (?, ?, ?, ?)
                        """, (guild.id, boss, expiry, datetime.now(timezone.utc).isoformat()))
                        await db.commit()
                except Exception as e:
                    logger.error(f"Error sending archon hunt notification to {guild.id}: {e}")
                    continue
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
            if not bot.is_ready():
                return
            
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, guild_id, user_id, channel_id, reminder_text, remind_at, recurrence_rule
                    FROM reminders
                    WHERE sent = 0 AND datetime(remind_at) <= datetime('now')
                """)
                due_reminders = await cur.fetchall()
            
            for reminder_id, guild_id, user_id, channel_id, reminder_text, remind_at, recurrence_rule in due_reminders:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    user = guild.get_member(user_id)
                    if not user:
                        continue
                    
                    channel = guild.get_channel(channel_id) if channel_id else None
                    prefer_dm = (await get_guild_setting(guild_id, "reminders_prefer_dm") or "").lower() in ("1", "true", "yes")
                    if await get_quieter_mode(guild_id):
                        prefer_dm = True  # Quieter mode: prefer DM to avoid channel pings
                    from commands.general.reminder import ReminderSnoozeView, store_snooze_context

                    sent = False
                    sent_message = None
                    if prefer_dm or not channel or not isinstance(channel, discord.TextChannel):
                        try:
                            embed = obsidian_embed(
                                "⏰ Reminder",
                                f"**{reminder_text}**\n\n*From {guild.name}*",
                                color=discord.Color.blue(),
                                client=bot,
                            )
                            sent_message = await safe_dm(user,embed=embed, view=ReminderSnoozeView())
                            sent = True
                        except Exception:
                            pass  # User has DMs disabled
                    if not sent and channel and isinstance(channel, discord.TextChannel):
                        embed = obsidian_embed(
                            "⏰ Reminder",
                            f"{user.mention}\n**{reminder_text}**",
                            color=discord.Color.blue(),
                            client=bot,
                        )
                        from core.safe_send import safe_channel_send

                        sent_message = await safe_channel_send(
                            channel,
                            dm_user=user,
                            embed=embed,
                            view=ReminderSnoozeView(),
                        )

                    if sent_message is not None:
                        await store_snooze_context(
                            sent_message.id, guild_id, user_id, channel_id, reminder_text
                        )
                    
                    # Mark as sent and optionally re-insert recurring reminder
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("""
                            UPDATE reminders SET sent = 1 WHERE id = ?
                        """, (reminder_id,))
                        if recurrence_rule:
                            try:
                                from commands.general.reminder import _next_recurrence
                                remind_dt = datetime.fromisoformat(remind_at.replace("Z", "+00:00")) if isinstance(remind_at, str) else remind_at
                                next_at = _next_recurrence(remind_dt, recurrence_rule)
                                if next_at:
                                    await db.execute("""
                                        INSERT INTO reminders (guild_id, user_id, channel_id, reminder_text, remind_at, created_at, sent, recurrence_rule)
                                        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                                    """, (guild_id, user_id, channel_id, reminder_text, next_at.isoformat(), now_utc().isoformat(), recurrence_rule))
                            except Exception as re:
                                logger.debug(f"Recurring reminder re-insert: {re}")
                        await db.commit()
                except Exception as e:
                    logger.error(f"Error sending reminder {reminder_id}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in reminder_check_loop: {e}", exc_info=True)
    
    @reminder_check_loop.before_loop
    async def before_reminder_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def poll_close_loop():
        """Close expired polls and post final results embeds (QoL #20)."""
        try:
            if not bot.is_ready():
                return
            from core.poll_utils import close_expired_poll
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, guild_id, channel_id, message_id, question, options, creator_id
                    FROM polls
                    WHERE COALESCE(closed, 0) = 0
                      AND ends_at IS NOT NULL
                      AND TRIM(ends_at) != ''
                      AND datetime(ends_at) <= datetime('now')
                    LIMIT 25
                """)
                rows = await cur.fetchall()
            for row in rows:
                try:
                    await close_expired_poll(bot, row)
                except Exception as exc:
                    logger.debug("[poll] auto-close failed: %s", exc)
        except Exception as e:
            logger.error(f"Error in poll_close_loop: {e}", exc_info=True)

    @poll_close_loop.before_loop
    async def before_poll_close_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def scheduled_messages_loop():
        """Send scheduled messages when due."""
        try:
            if not bot.is_ready():
                return
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, guild_id, channel_id, message_content
                    FROM scheduled_messages
                    WHERE sent = 0 AND datetime(send_at) <= datetime('now')
                """)
                due = await cur.fetchall()
            for row_id, guild_id, channel_id, msg_content in due:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    channel = guild.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        continue
                    await channel.send(msg_content)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("UPDATE scheduled_messages SET sent = 1 WHERE id = ?", (row_id,))
                        await db.commit()
                except Exception as e:
                    logger.error(f"[schedule] Error sending scheduled message {row_id}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[schedule] Error in scheduled_messages_loop: {e}", exc_info=True)

    @scheduled_messages_loop.before_loop
    async def before_scheduled_messages_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=5)  # Check every 5 minutes for Twitch streams
    async def twitch_check_loop():
        """Check for Twitch streamers going live."""
        try:
            if not bot.is_ready():
                return
            
            # Get Twitch access token
            import os
            from commands.general.twitch import get_twitch_access_token, check_twitch_stream
            
            access_token = await get_twitch_access_token()
            if not access_token:
                return  # Twitch API not configured
            
            # Check all guilds with Twitch enabled
            for guild in bot.guilds:
                try:
                    async with aiosqlite.connect(DB_PATH) as db:
                        # Check if ping_role_id column exists
                        try:
                            cur = await db.execute("PRAGMA table_info(twitch_settings)")
                            columns = await cur.fetchall()
                            column_names = [col[1] for col in columns]
                            has_ping_role = "ping_role_id" in column_names
                        except Exception:
                            has_ping_role = False
                        
                        if has_ping_role:
                            cur = await db.execute("""
                                SELECT channel_id, enabled, ping_role_id FROM twitch_settings WHERE guild_id=?
                            """, (guild.id,))
                        else:
                            cur = await db.execute("""
                                SELECT channel_id, enabled FROM twitch_settings WHERE guild_id=?
                            """, (guild.id,))
                        settings_row = await cur.fetchone()
                        
                        if not settings_row or not settings_row[1]:
                            continue
                        
                        channel_id = settings_row[0]
                        ping_role_id = settings_row[2] if has_ping_role and len(settings_row) > 2 else None
                        channel = guild.get_channel(channel_id)
                        if not isinstance(channel, discord.TextChannel):
                            continue
                        
                        ping_role = guild.get_role(ping_role_id) if ping_role_id else None
                        
                        # Get streamers for this guild
                        cur = await db.execute("""
                            SELECT streamer_name, last_live_status FROM twitch_streamers
                            WHERE guild_id=?
                        """, (guild.id,))
                        streamers = await cur.fetchall()
                        
                        for streamer_name, last_status in streamers:
                            stream_data = await check_twitch_stream(streamer_name, access_token)
                            is_live = stream_data is not None
                            
                            # Only notify if going from offline to live
                            if is_live and not last_status:
                                # Streamer just went live
                                title = stream_data.get("title", "No title")
                                game = stream_data.get("game_name", "Unknown game")
                                viewer_count = stream_data.get("viewer_count", 0)
                                
                                embed = obsidian_embed(
                                    f"🔴 {streamer_name} is now live!",
                                    f"**Title:** {title}\n**Game:** {game}\n**Viewers:** {viewer_count}\n\n"
                                    f"https://twitch.tv/{streamer_name}",
                                    color=discord.Color.purple(),
                                    client=bot,
                                )
                                
                                try:
                                    # Ping role if configured
                                    message_content = ping_role.mention if ping_role else None
                                    await channel.send(content=message_content, embed=embed)
                                    
                                    # Update status
                                    await db.execute("""
                                        UPDATE twitch_streamers SET last_live_status=1, last_notified_at=?
                                        WHERE guild_id=? AND streamer_name=?
                                    """, (now_utc().isoformat(), guild.id, streamer_name))
                                    await db.commit()
                                except Exception as e:
                                    logger.error(f"Error sending Twitch notification: {e}")
                            
                            elif not is_live and last_status:
                                # Streamer went offline
                                await db.execute("""
                                    UPDATE twitch_streamers SET last_live_status=0
                                    WHERE guild_id=? AND streamer_name=?
                                """, (guild.id, streamer_name))
                                await db.commit()
                
                except Exception as e:
                    logger.error(f"Error in twitch_check_loop for guild {guild.id}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"Error in twitch_check_loop: {e}", exc_info=True)
    
    @twitch_check_loop.before_loop
    async def before_twitch_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def stale_ticket_reminder_loop():
        """Remind staff about idle tickets; auto-close if still idle after warning."""
        try:
            from core.utils import get_mod_role
            for guild in bot.guilds:
                try:
                    stale_days = 3
                    days_setting = await get_guild_setting(guild.id, "stale_ticket_days")
                    if days_setting and days_setting.isdigit():
                        stale_days = int(days_setting)
                    cutoff = now_utc() - timedelta(days=stale_days)
                    cutoff_iso = cutoff.isoformat()
                    # Auto-close configured? (default True unless disabled)
                    autoclose_setting = await get_guild_setting(guild.id, "ticket_autoclose")
                    autoclose_enabled = autoclose_setting != "0"

                    async with aiosqlite.connect(DB_PATH) as db:
                        # --- Step 1: warn tickets not yet warned ---
                        cur = await db.execute("""
                            SELECT id, channel_id, ticket_id, subject, last_activity_at
                            FROM tickets
                            WHERE guild_id=? AND status='open'
                              AND (stale_reminder_sent IS NULL OR stale_reminder_sent=0)
                              AND (last_activity_at IS NULL OR last_activity_at < ?)
                        """, (guild.id, cutoff_iso))
                        warn_rows = await cur.fetchall()

                        # --- Step 2: auto-close tickets already warned + still idle ---
                        # "24h after warning sent" ≈ the loop runs daily; if warned AND still past cutoff, close
                        autoclose_cutoff = (now_utc() - timedelta(days=stale_days + 1)).isoformat()
                        cur2 = await db.execute("""
                            SELECT id, channel_id, ticket_id, user_id, subject
                            FROM tickets
                            WHERE guild_id=? AND status='open' AND stale_reminder_sent=1
                              AND (last_activity_at IS NULL OR last_activity_at < ?)
                        """, (guild.id, autoclose_cutoff))
                        close_rows = await cur2.fetchall()

                    # Send warnings
                    for tid, ch_id, ticket_id, subject, last_at in warn_rows:
                        channel = guild.get_channel(int(ch_id))
                        if not isinstance(channel, discord.TextChannel):
                            continue
                        mod_role = get_mod_role(guild)
                        mention = ""
                        if not await get_quieter_mode(guild.id) and mod_role:
                            mention = mod_role.mention
                        autoclose_note = f"\n\n⚠️ This ticket will be **auto-closed in ~24 hours** if there is no activity." if autoclose_enabled else ""
                        try:
                            await channel.send(
                                content=mention or None,
                                embed=obsidian_embed(
                                    "⏰ Ticket Inactive",
                                    f"This ticket has had no activity for **{stale_days}+ days**.\n"
                                    f"**Last activity:** {last_at[:19] if last_at else '—'}\n\n"
                                    f"Staff: please respond or close this ticket.{autoclose_note}",
                                    color=discord.Color.orange(),
                                    client=bot,
                                ),
                            )
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute(
                                    "UPDATE tickets SET stale_reminder_sent=1 WHERE id=?",
                                    (tid,),
                                )
                                await db.commit()
                        except Exception as e:
                            logger.warning(f"[stale_ticket] Could not send reminder for ticket {ticket_id}: {e}")

                    # Auto-close stale warned tickets
                    if autoclose_enabled:
                        for tid, ch_id, ticket_id, user_id, subject in close_rows:
                            channel = guild.get_channel(int(ch_id))
                            if not isinstance(channel, discord.TextChannel):
                                continue
                            try:
                                now_iso = now_utc().isoformat()
                                # Generate transcript first
                                from commands.tickets.ticket import _build_transcript, _send_transcript_to_log, _get_ticket_row_by_id
                                ticket_row = await _get_ticket_row_by_id(tid)
                                transcript_bytes = await _build_transcript(channel)
                                file_name = f"ticket-{ticket_id}.txt"
                                log_ch_id, log_msg_id = None, None
                                if ticket_row:
                                    log_ch_id, log_msg_id = await _send_transcript_to_log(guild, ticket_row, transcript_bytes, file_name)

                                async with aiosqlite.connect(DB_PATH) as db:
                                    await db.execute(
                                        "UPDATE tickets SET status='closed', closed_at=?, closed_by=?, transcript_channel_id=?, transcript_message_id=? WHERE id=?",
                                        (now_iso, bot.user.id if bot.user else 0, log_ch_id, log_msg_id, tid),
                                    )
                                    await db.commit()

                                await channel.send(embed=obsidian_embed(
                                    "🔒 Ticket Auto-Closed",
                                    f"This ticket (`{ticket_id}`) was automatically closed due to inactivity "
                                    f"(**{stale_days + 1}+ days** with no messages).\n\n"
                                    "A transcript has been saved. This channel will be deleted in 30 seconds.",
                                    color=discord.Color.dark_grey(), client=bot,
                                ))

                                # DM the ticket owner
                                try:
                                    owner = guild.get_member(int(user_id)) or await bot.fetch_user(int(user_id))
                                    if owner:
                                        await owner.send(embed=obsidian_embed(
                                            "🔒 Your Ticket Was Closed",
                                            f"Your ticket **{ticket_id}** in **{guild.name}** was automatically closed "
                                            f"after {stale_days + 1} days of inactivity.\n\n"
                                            "If you still need help, open a new ticket with `/community ticket`.",
                                            color=discord.Color.dark_grey(), client=bot,
                                        ))
                                except Exception:
                                    pass

                                import asyncio as _asyncio
                                await _asyncio.sleep(30)
                                await channel.delete(reason="Auto-closed: ticket idle too long")
                                logger.info(f"[stale_ticket] Auto-closed idle ticket {ticket_id} in guild {guild.id}")
                            except Exception as e:
                                logger.warning(f"[stale_ticket] Could not auto-close ticket {ticket_id}: {e}")
                except Exception as e:
                    logger.error(f"[stale_ticket] Error for guild {guild.id}: {e}", exc_info=True)
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
            if not bot.is_ready():
                return
            import aiohttp
            import xml.etree.ElementTree as ET
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id=UCZ8h7R8l2LoXzbc-GufOyKw"
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status != 200:
                            return
                        text = await r.text()
                except Exception:
                    return
            root = ET.fromstring(text)
            ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
            seen = set()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT item_id FROM integration_seen WHERE source='youtube'")
                for row in await cur.fetchall():
                    seen.add(row[0])
            for entry in entries[:3]:
                vid_id = None
                title = None
                link = None
                vid_el = entry.find("{http://www.youtube.com/xml/schemas/2015}videoId")
                if vid_el is not None and vid_el.text:
                    vid_id = vid_el.text.strip()
                tit_el = entry.find("{http://www.w3.org/2005/Atom}title")
                if tit_el is not None and tit_el.text:
                    title = tit_el.text.strip()
                for link_el in entry.findall("{http://www.w3.org/2005/Atom}link"):
                    if link_el.get("rel") == "alternate":
                        link = link_el.get("href", "")
                        break
                if not vid_id and link:
                    if "v=" in link:
                        vid_id = link.split("v=")[-1].split("&")[0]
                if not link and vid_id:
                    link = f"https://www.youtube.com/watch?v={vid_id}"
                if not vid_id:
                    vid_id = link or title or ""
                if not vid_id or vid_id in seen:
                    continue
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "INSERT OR IGNORE INTO integration_seen (source, item_id, created_at) VALUES ('youtube', ?, ?)",
                        (vid_id[:500], now_utc().isoformat()),
                    )
                    await db.commit()
                for guild in bot.guilds:
                    ch_id = await get_guild_setting(guild.id, "youtube_notify_channel_id")
                    if not ch_id:
                        continue
                    ch = guild.get_channel(int(ch_id))
                    if not isinstance(ch, discord.TextChannel):
                        continue
                    try:
                        await ch.send(
                            embed=obsidian_embed(
                                "New Warframe Video",
                                f"**{title or 'New upload'}**\n\n{link or ''}",
                                color=discord.Color.red(),
                                client=bot,
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"[youtube] Error notifying guild {guild.id}: {e}")
        except Exception as e:
            logger.error(f"[youtube] Error in youtube_check_loop: {e}", exc_info=True)

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
            if not bot.is_ready():
                return
            from database import get_guild_setting, set_guild_setting

            cutoff = (now_utc() - timedelta(minutes=30)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT id, guild_id, channel_id, message_id
                    FROM lfg_posts
                    WHERE status='OPEN' AND datetime(created_at) <= datetime(?)
                    """,
                    (cutoff,),
                )
                rows = await cur.fetchall()
            for lfg_id, guild_id, channel_id, message_id in rows:
                try:
                    if await get_guild_setting(int(guild_id), f"lfg_bumped:{lfg_id}"):
                        continue
                    guild = bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                    ch = guild.get_channel(int(channel_id))
                    if not isinstance(ch, discord.TextChannel):
                        continue
                    msg = await ch.fetch_message(int(message_id))
                    if msg.thread and getattr(msg.thread, "message_count", 0) > 1:
                        continue
                    from core.safe_send import safe_channel_send
                    await safe_channel_send(
                        ch,
                        content=f"👋 Still looking for squad — {msg.jump_url}",
                        delete_after=3600,
                    )
                    await set_guild_setting(int(guild_id), f"lfg_bumped:{lfg_id}", "1")
                except Exception as exc:
                    logger.debug("[lfg_bump] %s: %s", lfg_id, exc)
        except Exception as e:
            logger.error(f"[lfg_bump] loop error: {e}", exc_info=True)

    @lfg_bump_loop.before_loop
    async def before_lfg_bump_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=20)
    async def lfg_poster_nudge_loop():
        """DM LFG creators after ~2h with no thread replies."""
        try:
            if not bot.is_ready():
                return
            from database import get_guild_setting, set_guild_setting

            cutoff = (now_utc() - timedelta(hours=2)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT id, guild_id, creator_id, message_id, channel_id, mission_type
                    FROM lfg_posts
                    WHERE status='OPEN' AND datetime(created_at) <= datetime(?)
                    """,
                    (cutoff,),
                )
                rows = await cur.fetchall()
            for lfg_id, guild_id, creator_id, message_id, channel_id, mission in rows:
                try:
                    if await get_guild_setting(int(guild_id), f"lfg_creator_nudged:{lfg_id}"):
                        continue
                    guild = bot.get_guild(int(guild_id))
                    if not guild:
                        continue
                    ch = guild.get_channel(int(channel_id))
                    if not isinstance(ch, discord.TextChannel):
                        continue
                    msg = await ch.fetch_message(int(message_id))
                    if msg.thread and getattr(msg.thread, "message_count", 0) > 1:
                        continue
                    user = guild.get_member(int(creator_id)) or bot.get_user(int(creator_id))
                    if not user:
                        continue
                    from core.quiet_hours import in_quiet_hours
                    if await in_quiet_hours(int(guild_id), int(creator_id)):
                        continue
                    await safe_dm(user,
                        embed=obsidian_embed(
                            "👋 Still looking for squad?",
                            f"Your **{mission}** LFG has had no replies for 2+ hours.\n\n"
                            f"[Jump to post]({msg.jump_url}) — bump in chat or mark filled when done.",
                            client=bot,
                        )
                    )
                    await set_guild_setting(int(guild_id), f"lfg_creator_nudged:{lfg_id}", "1")
                except Exception as exc:
                    logger.debug("[lfg_nudge] %s: %s", lfg_id, exc)
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
