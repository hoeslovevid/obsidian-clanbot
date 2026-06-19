"""Event reminder and go-live notification cycle (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.channels import ensure_core_channels, resolve_channel_id
from core.safe_send import safe_dm
from core.utils import obsidian_embed
from database import DB_PATH, get_guild_setting, get_quieter_mode, now_utc

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

async def run_recurring_event_cycle(bot: discord.Client) -> None:
    """Create events from recurring templates when scheduled time matches."""
    from core.channels import ensure_core_channels
    from views import RSVPView
    now = now_utc()
    current_week = now.strftime("%Y-W%V")
    current_weekday = now.weekday()
    current_hour = now.hour

    for guild in bot.guilds:
        try:
            await ensure_core_channels(guild)
            events_id = await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
            ch = guild.get_channel(events_id) if events_id else None
            if not isinstance(ch, discord.TextChannel):
                continue

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT id, title, description, day_of_week, hour_utc, duration_hours, role_id, created_by, last_created_week
                    FROM recurring_event_templates
                    WHERE guild_id=? AND is_active=1
                """, (guild.id,))
                templates = await cur.fetchall()

            for tid, title, desc, dow, hour, dur, role_id, creator_id, last_week in templates:
                if dow != current_weekday or hour != current_hour:
                    continue
                if last_week == current_week:
                    continue

                ts = int(now.replace(minute=0, second=0, microsecond=0).timestamp())
                end_ts = ts + (dur * 3600)
                mention = ""
                if not await get_quieter_mode(guild.id) and int(role_id or 0):
                    role = guild.get_role(int(role_id))
                    if role:
                        mention = role.mention

                embed = obsidian_embed(
                    f"≡ƒ£é Ops Order ΓÇó {title}",
                    f"**When:** <t:{ts}:F>  _( <t:{ts}:R> )_\n\n"
                    f"**Ends:** <t:{end_ts}:t>  _( <t:{end_ts}:R> )_\n\n"
                    f"**Briefing:**\n{desc or 'ΓÇö'}",
                    color=discord.Color.dark_grey(),
                    client=bot,
                )
                rsvp_empty = RSVPView.format_rsvp_summary({"GOING": 0, "MAYBE": 0, "NO": 0})
                embed.add_field(name="RSVP", value=rsvp_empty, inline=False)
                embed.set_footer(text=rsvp_empty)

                try:
                    msg = await ch.send(content=mention or None, embed=embed, view=RSVPView())
                    thread_id = 0
                    try:
                        from commands.events.event_create import _maybe_create_event_thread
                        tid_val = await _maybe_create_event_thread(msg, ch, title, datetime.fromtimestamp(ts, tz=timezone.utc))
                        thread_id = tid_val or 0
                    except Exception:
                        thread_id = 0

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("""
                            INSERT INTO events(guild_id,message_id,creator_id,title,start_ts,end_ts,description,role_id,created_at,reminder_sent,ended,recap_posted,recap_message_id,thread_id)
                            VALUES(?,?,?,?,?,?,?,?,?,0,0,0,0,?)
                        """, (guild.id, msg.id, creator_id, title, ts, end_ts, desc or "", role_id or 0, now.isoformat(), thread_id))
                        await db.execute(
                            "UPDATE recurring_event_templates SET last_created_week=? WHERE id=?",
                            (current_week, tid),
                        )
                        await db.commit()
                except Exception as e:
                    logger.error(f"[recurring_event] Error creating event for guild {guild.id} template {tid}: {e}")
        except Exception as e:
            logger.error(f"[recurring_event] Error for guild {guild.id}: {e}", exc_info=True)


async def run_event_end_cycle(bot: discord.Client) -> None:
    """Post end-of-event recaps and mark events ended."""
    now_ts = int(now_utc().timestamp())
    for guild in bot.guilds:
        events_id = await resolve_channel_id(guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
        ch = guild.get_channel(events_id) if events_id else None
        if not isinstance(ch, discord.TextChannel):
            continue

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT message_id, title, start_ts, end_ts, role_id, thread_id
                FROM events
                WHERE guild_id=? AND ended=0 AND end_ts IS NOT NULL AND end_ts <= ?
                """,
                (guild.id, now_ts),
            )
            events_to_end = await cur.fetchall()

        for message_id, title, start_ts, end_ts, role_id, thread_id in events_to_end:
            recap_message_id = 0
            try:
                # Fetch RSVP counts
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT response, COUNT(*) FROM event_rsvps WHERE guild_id=? AND message_id=? GROUP BY response",
                        (guild.id, int(message_id)),
                    )
                    rows = await cur.fetchall()
                    counts = {"GOING": 0, "MAYBE": 0, "NO": 0}
                    for r, c in rows:
                        counts[str(r)] = int(c)

                    # Get GOING users (limit)
                    cur = await db.execute(
                        "SELECT user_id FROM event_rsvps WHERE guild_id=? AND message_id=? AND response='GOING'",
                        (guild.id, int(message_id)),
                    )
                    going_users = [int(x[0]) for x in await cur.fetchall()]

                mention = ""
                if not await get_quieter_mode(guild.id) and int(role_id or 0):
                    role = guild.get_role(int(role_id))
                    if role:
                        mention = role.mention

                going_list = ", ".join(f"<@{uid}>" for uid in going_users[:25]) if going_users else "ΓÇö"
                if len(going_users) > 25:
                    going_list += f" (+{len(going_users) - 25} more)"

                recap_embed = obsidian_embed(
                    "Γ£à Ops Debrief ΓÇó Event Ended",
                    f"**{title}**\n"
                    f"**Started:** <t:{int(start_ts)}:F>\n"
                    f"**Ended:** <t:{int(end_ts)}:F>\n\n"
                    f"Γ£à Going: **{counts['GOING']}**  |  Γ¥ö Maybe: **{counts['MAYBE']}**  |  Γ¥î Can't: **{counts['NO']}**\n\n"
                    f"**Attendees (Going):**\n{going_list}",
                    color=discord.Color.green(),
                    client=bot,
                )

                # Prefer posting in thread
                posted = False
                if thread_id:
                    thread = guild.get_thread(int(thread_id))
                    if thread:
                        try:
                            msg = await thread.send(content=mention if mention else None, embed=recap_embed)
                            recap_message_id = msg.id
                            posted = True
                        except Exception:
                            posted = False

                if not posted:
                    msg = await ch.send(content=mention if mention else None, embed=recap_embed)
                    recap_message_id = msg.id

                # Try to edit original event post to show ended (and remove view)
                try:
                    original = await ch.fetch_message(int(message_id))
                    if original and original.embeds:
                        embed = original.embeds[0]
                        embed.color = discord.Color.light_grey()
                        embed.set_footer(text="Γ£à Event Ended")
                        await original.edit(embed=embed, view=None)
                except Exception:
                    pass

                # Item 65 ΓÇö archive the discussion thread with an [ENDED] prefix
                if thread_id:
                    try:
                        thread = guild.get_thread(int(thread_id)) or await bot.fetch_channel(int(thread_id))
                        if isinstance(thread, discord.Thread):
                            new_name = thread.name if thread.name.startswith("[ENDED]") else f"[ENDED] {thread.name}"
                            new_name = new_name[:100]
                            await thread.edit(name=new_name, archived=True, locked=False)
                    except Exception as _e:
                        logger.debug(f"[events] could not archive thread {thread_id}: {_e}")

                # Mark ended in DB
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE events SET ended=1, recap_posted=1, recap_message_id=? WHERE guild_id=? AND message_id=?",
                        (int(recap_message_id or 0), guild.id, int(message_id)),
                    )
                    await db.commit()
            except Exception as e:
                logger.error(f"[events] Error ending event {message_id} in {guild.id}: {e}", exc_info=True)
                continue

async def run_event_rsvp_reminder_cycle(bot: discord.Client) -> None:
    """DM GOING users when their event is 30-35 minutes away."""
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

