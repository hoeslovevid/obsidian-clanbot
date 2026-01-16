"""
Background tasks for the bot.
This module contains all periodic tasks and loops.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord
from discord.ext import tasks  # type: ignore

from database import DB_PATH, now_utc, get_guild_setting, add_coins, add_xp, get_user_xp
from channels import resolve_channel_id, delete_temp_vc_and_panel
from warframe_api import get_baro_status, get_all_cycles, fetch_invasions, fetch_archon_hunt_data, fetch_events_data
from utils import obsidian_embed, ECONOMY_ENABLED, COINS_PER_MINUTE_VOICE, MIN_VOICE_MINUTES_FOR_REWARD, XP_ENABLED, XP_PER_MINUTE_VOICE

# Import Baro embed builder (lazy import to avoid circular dependency)
def get_baro_embed_builder():
    """Lazy import to avoid circular dependency."""
    from commands.warframe.baro import build_baro_embed
    return build_baro_embed

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


async def check_ended_giveaways(bot):
    """Check for ended giveaways and select winners."""
    from commands.giveaways.giveaway_end import end_giveaway
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id FROM giveaways
            WHERE ended = 0 AND datetime(end_time) <= datetime('now')
        """)
        ended_giveaways = await cur.fetchall()
    
    for (giveaway_id,) in ended_giveaways:
        try:
            success, message, winners = await end_giveaway(giveaway_id, bot)
            if success:
                logger.info(f"[giveaway] Ended giveaway {giveaway_id}, selected {len(winners)} winner(s)")
        except Exception as e:
            logger.error(f"[giveaway] Error ending giveaway {giveaway_id}: {e}", exc_info=True)


async def check_and_notify_baro_arrival(bot):
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
            import json
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
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
                        (guild.id,)
                    )
                    setting = await cur.fetchone()
                
                if not setting or not setting[1]:  # Not enabled or not set
                    continue
            except Exception as e:
                logger.error(f"Error checking baro notification settings for guild {guild.id}: {e}")
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


def setup_tasks(bot):
    """Set up all background tasks. Must be called after bot is created."""
    
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
                        logger.error(f"[economy] Error processing voice reward for {user_id} in {guild.id}: {e}")
                        continue

    @voice_reward_loop.before_loop
    async def before_voice_reward_loop():
        await bot.wait_until_ready()

    @tasks.loop(hours=1)  # Check every hour for Baro
    async def baro_check_loop():
        """Check for Baro Ki'Teer arrivals and send notifications."""
        try:
            await check_and_notify_baro_arrival(bot)
        except Exception as e:
            logger.error(f"Error in baro_check_loop: {e}", exc_info=True)

    @baro_check_loop.before_loop
    async def before_baro_check_loop():
        await bot.wait_until_ready()

    @tasks.loop(minutes=1)  # Update every minute
    async def baro_live_update_loop():
        """Update live Baro messages with current time remaining."""
        try:
            is_active, baro_data = await get_baro_status()
            
            if not is_active or not baro_data:
                # Baro is not active, clean up all live messages
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
                    
                    # Update the message
                    await message.edit(embed=updated_embed)
                    
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

    @tasks.loop(hours=1)  # Check every hour for expired LFG posts
    async def lfg_expire_loop():
        """Auto-expire LFG posts that have passed their expiry time."""
        try:
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

    @tasks.loop(minutes=5)  # Check every 5 minutes for cycle changes
    async def cycle_check_loop():
        """Check for cycle changes and send notifications."""
        try:
            # Verify bot is ready
            if not bot.is_ready():
                return
            cycles_data = await get_all_cycles()
            
            if not cycles_data:
                return
            
            # Check each cycle type
            for cycle_type, data in cycles_data.items():
                if not data:
                    continue
                
                expiry = data.get('expiry', '')
                if not expiry:
                    continue
                
                try:
                    expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                    if not expiry_time:
                        continue
                    
                    now = datetime.now(timezone.utc)
                    time_until_change = expiry_time - now
                    
                    # Only notify if cycle is about to change (within 2 minutes)
                    if 0 <= time_until_change.total_seconds() <= 120:
                        # Check if we've already notified for this cycle change
                        cycle_state = None
                        cycle_display = None
                        
                        if cycle_type == 'cetus':
                            is_day = data.get('isDay', False)
                            cycle_state = 'day' if is_day else 'night'
                            cycle_display = "☀️ Day" if is_day else "🌙 Night"
                        elif cycle_type == 'vallis':
                            is_warm = data.get('isWarm', False)
                            cycle_state = 'warm' if is_warm else 'cold'
                            cycle_display = "🔥 Warm" if is_warm else "❄️ Cold"
                        elif cycle_type == 'cambion':
                            state = data.get('state', '').lower()
                            cycle_state = state
                            cycle_display = "🔴 Fass" if state == 'fass' else "🟢 Vome" if state == 'vome' else state.title()
                        
                        if not cycle_state:
                            continue
                        
                        # Map cycle types to database columns and display names
                        column_map = {
                            'cetus': ('cetus_enabled', 'Cetus (Plains of Eidolon)'),
                            'vallis': ('fortuna_enabled', 'Fortuna (Orb Vallis)'),
                            'cambion': ('deimos_enabled', 'Deimos (Cambion Drift)'),
                        }
                        
                        column, display_name = column_map.get(cycle_type, (None, None))
                        if not column:
                            continue
                        
                        # Send notifications to all guilds that have it enabled
                        for guild in bot.guilds:
                            try:
                                async with aiosqlite.connect(DB_PATH) as db:
                                    cur = await db.execute(
                                        f"SELECT channel_id, {column} FROM cycle_notification_settings WHERE guild_id=?",
                                        (guild.id,)
                                    )
                                    setting = await cur.fetchone()
                                
                                if not setting or not setting[1]:  # Not enabled
                                    continue
                            except Exception as e:
                                logger.error(f"Error checking cycle notification settings for guild {guild.id}: {e}")
                                continue
                            
                            channel_id = setting[0]
                            if not channel_id:
                                continue
                            
                            ch = guild.get_channel(channel_id)
                            if not isinstance(ch, discord.TextChannel):
                                continue
                            
                            # Check if we've already notified for this cycle change
                            async with aiosqlite.connect(DB_PATH) as db:
                                cur = await db.execute("""
                                    SELECT 1 FROM cycle_notifications_sent
                                    WHERE guild_id=? AND cycle_type=? AND cycle_state=? AND notified_at > datetime('now', '-5 minutes')
                                """, (guild.id, cycle_type, cycle_state))
                                already_notified = await cur.fetchone()
                            
                            if already_notified:
                                continue
                            
                            # Calculate when the new cycle will end
                            # Cycles alternate, so we need to calculate the next expiry
                            # Cetus: Day/Night cycles are ~150 minutes each
                            # Fortuna: Warm/Cold cycles are ~26 minutes each  
                            # Deimos: Fass/Vome cycles are ~100 minutes each
                            cycle_durations = {
                                'cetus': 150 * 60,  # 150 minutes in seconds
                                'vallis': 26 * 60,  # 26 minutes in seconds
                                'cambion': 100 * 60,  # 100 minutes in seconds
                            }
                            
                            duration_seconds = cycle_durations.get(cycle_type, 0)
                            next_expiry_time = expiry_time + timedelta(seconds=duration_seconds)
                            
                            # Send notification
                            desc = f"**{display_name}** cycle is changing!\n\n"
                            desc += f"**New State:** {cycle_display}\n"
                            desc += f"**Changes At:** <t:{int(expiry_time.timestamp())}:F>\n"
                            desc += f"**Ends At:** <t:{int(next_expiry_time.timestamp())}:F> _(<t:{int(next_expiry_time.timestamp())}:R>)_"
                            
                            embed = obsidian_embed(
                                f"🌍 Cycle Change: {display_name}",
                                desc,
                                color=discord.Color.blue(),
                                client=bot,
                            )
                            
                            try:
                                await ch.send(embed=embed)
                                
                                # Record notification
                                async with aiosqlite.connect(DB_PATH) as db:
                                    await db.execute("""
                                        INSERT INTO cycle_notifications_sent (guild_id, cycle_type, cycle_state, notified_at)
                                        VALUES (?, ?, ?, ?)
                                    """, (guild.id, cycle_type, cycle_state, datetime.now(timezone.utc).isoformat()))
                                    await db.commit()
                            except Exception as e:
                                logger.error(f"Error sending cycle notification to {guild.id}: {e}")
                                continue
                except Exception as e:
                    logger.error(f"Error processing {cycle_type} cycle: {e}")
                    continue
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
            invasions_data = await fetch_invasions()
            
            if not invasions_data:
                return
            
            # Get all notification settings
            for guild in bot.guilds:
                try:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute("""
                            SELECT reward_lower, reward_display, channel_id
                            FROM invasion_notification_settings
                            WHERE guild_id=? AND enabled=1
                        """, (guild.id,))
                        settings = await cur.fetchall()
                    
                    if not settings:
                        continue
                except Exception as e:
                    logger.error(f"Error checking invasion notification settings for guild {guild.id}: {e}")
                    continue
                
                # Check each invasion for matching rewards
                for inv in invasions_data:
                    invasion_id = inv.get("id", "")
                    if not invasion_id:
                        continue
                    
                    # Get rewards from both sides
                    attacker_reward = inv.get("attackerReward", {})
                    defender_reward = inv.get("defenderReward", {})
                    
                    rewards_found = []
                    
                    # Check attacker rewards
                    if attacker_reward:
                        counted_items = attacker_reward.get("countedItems", [])
                        for item in counted_items:
                            item_type = item.get("itemType", "").lower()
                            rewards_found.append(item_type)
                    
                    # Check defender rewards
                    if defender_reward:
                        counted_items = defender_reward.get("countedItems", [])
                        for item in counted_items:
                            item_type = item.get("itemType", "").lower()
                            rewards_found.append(item_type)
                    
                    # Check if any configured reward matches
                    for reward_lower, reward_display, channel_id in settings:
                        if reward_lower in rewards_found and channel_id:
                            # Check if we've already notified for this invasion
                            async with aiosqlite.connect(DB_PATH) as db:
                                cur = await db.execute("""
                                    SELECT 1 FROM invasion_notifications_sent
                                    WHERE guild_id=? AND invasion_id=? AND reward_lower=?
                                """, (guild.id, invasion_id, reward_lower))
                                already_notified = await cur.fetchone()
                            
                            if already_notified:
                                continue
                            
                            # Get channel
                            ch = guild.get_channel(channel_id)
                            if not isinstance(ch, discord.TextChannel):
                                continue
                            
                            # Build notification
                            node = inv.get("node", "Unknown Location")
                            attacker = inv.get("attackingFaction", "Unknown")
                            defender = inv.get("defendingFaction", "Unknown")
                            completion = inv.get("completion", 0)
                            eta = inv.get("eta", "")
                            
                            # Format ETA
                            eta_str = "Unknown"
                            if eta:
                                try:
                                    eta_time = dateparser.parse(eta, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
                                    if eta_time:
                                        time_remaining = eta_time - datetime.now(timezone.utc)
                                        hours = int(time_remaining.total_seconds() // 3600)
                                        minutes = int((time_remaining.total_seconds() % 3600) // 60)
                                        eta_str = f"{hours}h {minutes}m"
                                except Exception:
                                    pass
                            
                            # Get full reward list
                            reward_list = []
                            if attacker_reward:
                                items = attacker_reward.get("countedItems", [])
                                for item in items:
                                    item_type = item.get("itemType", "")
                                    if item_type.lower() == reward_lower:
                                        reward_list.append(f"**{attacker}:** {item_type}")
                            
                            if defender_reward:
                                items = defender_reward.get("countedItems", [])
                                for item in items:
                                    item_type = item.get("itemType", "")
                                    if item_type.lower() == reward_lower:
                                        reward_list.append(f"**{defender}:** {item_type}")
                            
                            desc = f"**Location:** {node}\n"
                            desc += f"**Factions:** {attacker} vs {defender}\n"
                            desc += f"**Progress:** {completion:.1f}%\n"
                            desc += f"**Time Remaining:** {eta_str}\n\n"
                            desc += "**Reward Found:**\n" + "\n".join(reward_list)
                            
                            embed = obsidian_embed(
                                f"⚔️ Invasion Alert: {reward_display}",
                                desc,
                                color=discord.Color.orange(),
                                client=bot,
                            )
                            
                            try:
                                await ch.send(embed=embed)
                                
                                # Record notification
                                async with aiosqlite.connect(DB_PATH) as db:
                                    await db.execute("""
                                        INSERT INTO invasion_notifications_sent (guild_id, invasion_id, reward_lower, notified_at)
                                        VALUES (?, ?, ?, ?)
                                    """, (guild.id, invasion_id, reward_lower, datetime.now(timezone.utc).isoformat()))
                                    await db.commit()
                            except Exception as e:
                                logger.error(f"Error sending invasion notification to {guild.id}: {e}")
                                continue
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

    @tasks.loop(minutes=1)  # Check every minute for ended giveaways
    async def giveaway_check_loop():
        """Check for ended giveaways and select winners."""
        try:
            await check_ended_giveaways(bot)
        except Exception as e:
            logger.error(f"[giveaway] Error in giveaway check loop: {e}", exc_info=True)
    
    async def before_giveaway_check_loop():
        await bot.wait_until_ready()
    
    giveaway_check_loop.before_loop(before_giveaway_check_loop)
    giveaway_check_loop.start()
    logger.info("[tasks] Started giveaway check loop")

    # Start all tasks with error handling
    tasks_to_start = [
        ('temp_vc_cleanup', temp_vc_cleanup),
        ('event_reminder_loop', event_reminder_loop),
        ('voice_reward_loop', voice_reward_loop),
        ('baro_check_loop', baro_check_loop),
        ('baro_live_update_loop', baro_live_update_loop),
        ('lfg_expire_loop', lfg_expire_loop),
        ('cycle_check_loop', cycle_check_loop),
        ('invasion_check_loop', invasion_check_loop),
        ('archon_check_loop', archon_check_loop),
        ('member_count_update_loop', member_count_update_loop),
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
    
    return started_tasks
