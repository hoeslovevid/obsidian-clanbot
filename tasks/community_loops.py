"""Reminders, polls, and scheduled messages (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, get_quieter_mode, now_utc

logger = logging.getLogger(__name__)


async def run_reminder_check_cycle(bot: discord.Client) -> None:
    """Check for due reminders and send them."""
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


async def run_poll_close_cycle(bot: discord.Client) -> None:
    """Close expired polls and post final results embeds."""
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


async def run_scheduled_messages_cycle(bot: discord.Client) -> None:
    """Send scheduled messages when due."""
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

