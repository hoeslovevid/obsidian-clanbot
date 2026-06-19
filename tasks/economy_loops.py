"""Voice economy background rewards (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
import os
from datetime import datetime

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.utils import (
    COINS_PER_MINUTE_VOICE,
    ECONOMY_ENABLED,
    MIN_VOICE_MINUTES_FOR_REWARD,
    XP_ENABLED,
    XP_PER_MINUTE_VOICE,
)
from database import (
    DB_PATH,
    add_coins,
    add_xp,
    check_voice_lifetime_achievements,
    get_user_xp,
    increment_activity_voice_minutes,
    now_utc,
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
