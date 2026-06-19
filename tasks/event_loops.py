"""Event reminder and go-live notification cycle (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.channels import resolve_channel_id
from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, get_quieter_mode, now_utc

logger = logging.getLogger(__name__)

EVENT_REMINDER_MINUTES_BEFORE = int(__import__("os").getenv("EVENT_REMINDER_MINUTES_BEFORE", "60"))
EVENTS_CHANNEL_ID = int(__import__("os").getenv("EVENTS_CHANNEL_ID", "0") or "0")
EVENTS_CHANNEL_NAME = __import__("os").getenv("EVENTS_CHANNEL_NAME", "ops-board")


async def run_event_reminder_cycle(bot: discord.Client) -> None:
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
            quieter = await get_quieter_mode(guild.id)
            if not quieter and int(role_id or 0):
                role = guild.get_role(int(role_id))
                if role:
                    mention = role.mention

            if ch:
                from core.safe_send import safe_channel_send

                await safe_channel_send(
                    ch,
                    content=mention if mention else None,
                    embed=obsidian_embed(
                        "⏳ Operation Reminder",
                        f"**{title}** begins in ~{EVENT_REMINDER_MINUTES_BEFORE} minutes.\n"
                        f"**Time:** <t:{int(start_ts)}:F>  _( <t:{int(start_ts)}:R> )_",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                )

            # DM users who RSVP'd GOING or MAYBE
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id FROM event_rsvps WHERE guild_id=? AND message_id=? AND response IN ('GOING','MAYBE')",
                    (guild.id, int(message_id)),
                )
                rsvp_users = await cur.fetchall()
            for (user_id,) in rsvp_users:
                try:
                    member = guild.get_member(int(user_id))
                    if member and not member.bot:
                        await safe_dm(member,
                            embed=obsidian_embed(
                                "⏳ Event Reminder",
                                f"**{title}** in {guild.name} begins in ~{EVENT_REMINDER_MINUTES_BEFORE} minutes!\n**Time:** <t:{int(start_ts)}:F>",
                                color=discord.Color.orange(),
                                client=bot,
                            ),
                        )
                except (discord.Forbidden, discord.HTTPException):
                    pass

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE events SET reminder_sent=1 WHERE guild_id=? AND message_id=?",
                    (guild.id, int(message_id)),
                )
                await db.commit()

            try:
                from core.music_player import try_start_event_soundtrack

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT soundtrack_query, soundtrack_started FROM events "
                        "WHERE guild_id=? AND message_id=?",
                        (guild.id, int(message_id)),
                    )
                    snd_row = await cur.fetchone()
                if snd_row:
                    snd_query, snd_started = snd_row
                    if snd_query and not int(snd_started or 0):
                        played = await try_start_event_soundtrack(
                            guild, bot, str(snd_query), event_title=str(title),
                        )
                        if played:
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute(
                                    "UPDATE events SET soundtrack_started=1 "
                                    "WHERE guild_id=? AND message_id=?",
                                    (guild.id, int(message_id)),
                                )
                                await db.commit()
            except Exception as e:
                logger.debug(f"[music] event reminder soundtrack failed: {e}")

        # Go-live soundtracks (event just started; bot already in event VC)
        try:
            from core.music_player import try_start_event_soundtrack

            live_start = now_ts - 300
            live_end = now_ts + 60
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT message_id, title, soundtrack_query FROM events "
                    "WHERE guild_id=? AND ended=0 AND soundtrack_started=0 "
                    "AND soundtrack_query IS NOT NULL AND soundtrack_query != '' "
                    "AND start_ts BETWEEN ? AND ?",
                    (guild.id, live_start, live_end),
                )
                live_rows = await cur.fetchall()
            for msg_id, evt_title, snd_query in live_rows:
                played = await try_start_event_soundtrack(
                    guild, bot, str(snd_query), event_title=str(evt_title),
                )
                if played:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE events SET soundtrack_started=1 WHERE guild_id=? AND message_id=?",
                            (guild.id, int(msg_id)),
                        )
                        await db.commit()
        except Exception as e:
            logger.debug(f"[music] event go-live soundtrack failed: {e}")

        # "Starting now" — ping GOING RSVPs when event begins
        try:
            live_lo = now_ts - 90
            live_hi = now_ts + 90
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT message_id, title, start_ts FROM events "
                    "WHERE guild_id=? AND COALESCE(ended,0)=0 AND COALESCE(live_sent,0)=0 "
                    "AND start_ts BETWEEN ? AND ?",
                    (guild.id, live_lo, live_hi),
                )
                live_events = await cur.fetchall()
            for msg_id, title, start_ts in live_events:
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT user_id FROM event_rsvps WHERE guild_id=? AND message_id=? AND response='GOING'",
                        (guild.id, int(msg_id)),
                    )
                    going = await cur.fetchall()
                for (uid,) in going:
                    try:
                        member = guild.get_member(int(uid))
                        if member and not member.bot:
                            await safe_dm(member,
                                embed=obsidian_embed(
                                    "🟢 Event starting now",
                                    f"**{title}** is live in **{guild.name}**!\n"
                                    f"<t:{int(start_ts)}:R>",
                                    color=discord.Color.green(),
                                    client=bot,
                                )
                            )
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE events SET live_sent=1 WHERE guild_id=? AND message_id=?",
                        (guild.id, int(msg_id)),
                    )
                    await db.commit()
        except Exception as e:
            logger.debug(f"[events] live ping failed: {e}")
