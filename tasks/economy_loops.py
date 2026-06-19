"""Voice economy background rewards (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import aiosqlite  # type: ignore
import dateparser  # type: ignore
import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import (
    COINS_PER_MINUTE_VOICE,
    ECONOMY_ENABLED,
    MIN_VOICE_MINUTES_FOR_REWARD,
    XP_ENABLED,
    XP_PER_MINUTE_VOICE,
    obsidian_embed,
)
from database import (
    DB_PATH,
    add_coins,
    add_xp,
    check_voice_lifetime_achievements,
    get_guild_setting,
    get_user_xp,
    increment_activity_voice_minutes,
    now_utc,
    set_guild_setting,
)

logger = logging.getLogger(__name__)


async def run_voice_reward_cycle(bot: discord.Client) -> None:
    if not ECONOMY_ENABLED:
        return

    from core.utils import feature_enabled  # Item 85 — per-guild kill switch
    from core.music_player import get_music_vc_bonus_multiplier, guild_is_playing_music
    now = now_utc()

    for guild in bot.guilds:
        try:
            if not await feature_enabled(guild.id, "economy_passive"):
                continue
        except Exception:
            pass
        music_bonus = 1.0
        try:
            if XP_ENABLED and await feature_enabled(guild.id, "music") and guild_is_playing_music(guild):
                music_bonus = await get_music_vc_bonus_multiplier(guild.id)
        except Exception:
            music_bonus = 1.0
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
                        # Item 72 — server-goal multipliers (≥ 1.0)
                        from core.utils import get_active_multiplier as _get_mult
                        coins_mult = await _get_mult(guild.id, "coins")
                        xp_mult = await _get_mult(guild.id, "xp")
                        vc_music_mult = 1.0
                        if (
                            music_bonus > 1.0
                            and guild.voice_client
                            and guild.voice_client.channel
                            and guild.voice_client.channel.id == channel_id
                        ):
                            vc_music_mult = music_bonus
                        coins = int(round(minutes_to_reward * COINS_PER_MINUTE_VOICE * coins_mult * vc_music_mult))

                        if coins > 0:
                            reason = f"Voice activity in #{channel.name}"
                            if vc_music_mult > 1.0:
                                reason += f" (music bonus {vc_music_mult:.2f}×)"
                            await add_coins(
                                guild.id,
                                user_id,
                                coins,
                                "VOICE",
                                reason,
                            )

                            # Award XP (if enabled)
                            if XP_ENABLED:
                                xp_amount = int(round(minutes_to_reward * XP_PER_MINUTE_VOICE * xp_mult * vc_music_mult))
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
                                        from core.utils import send_levelup_announcement
                                        await send_levelup_announcement(guild, user, level, xp, total_xp)
                            
                            # Update tracking
                            new_total = total_minutes + minutes_to_reward
                            await db.execute("""
                                UPDATE voice_activity
                                SET last_reward_at=?, total_minutes=?
                                WHERE guild_id=? AND user_id=? AND channel_id=?
                            """, (now.isoformat(), new_total, guild.id, user_id, channel_id))
                            await db.commit()

                            try:
                                await increment_activity_voice_minutes(
                                    guild.id, user_id, minutes_to_reward
                                )
                                await check_voice_lifetime_achievements(
                                    guild.id, user_id, bot
                                )
                            except Exception:
                                pass

                            # Item 106 — passive pet happiness boost while owner is in voice.
                            # +1/min < 80, +0.5/min 80–95, +0.1/min above 95, capped at 100.
                            try:
                                async with aiosqlite.connect(DB_PATH) as pdb:
                                    pcur = await pdb.execute(
                                        "SELECT id, happiness FROM pets WHERE guild_id=? AND user_id=?",
                                        (guild.id, user_id),
                                    )
                                    pet_row = await pcur.fetchone()
                                if pet_row:
                                    pet_id, happiness = pet_row
                                    new_h = float(happiness or 0)
                                    for _ in range(int(minutes_to_reward)):
                                        if new_h >= 100:
                                            break
                                        if new_h < 80:
                                            new_h += 1.0
                                        elif new_h < 95:
                                            new_h += 0.5
                                        else:
                                            new_h += 0.1
                                    new_h_int = min(100, int(round(new_h)))
                                    if new_h_int > int(happiness or 0):
                                        async with aiosqlite.connect(DB_PATH) as pdb:
                                            await pdb.execute(
                                                "UPDATE pets SET happiness=?, last_played_at=? WHERE id=?",
                                                (new_h_int, now.isoformat(), pet_id),
                                            )
                                            await pdb.commit()
                            except Exception as _pe:
                                logger.debug(f"[pet_voice_happiness] {_pe}")
                
                except Exception as e:
                    logger.error(f"[economy] Error processing voice reward for {user_id} in {guild.id}: {e}")
                    continue

async def run_pet_decay_reminder_cycle(bot: discord.Client) -> None:
    """DM users when their pet's hunger or happiness is low."""
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

async def run_daily_streak_reminder_cycle(bot: discord.Client) -> None:
    """DM opted-in users ~1 hour before their daily streak resets."""
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


async def run_investment_maturity_dm_cycle(bot: discord.Client) -> None:
    """DM opted-in users when their investment has matured."""
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

