"""Ticket SLA background checks (extracted from tasks/_core.py)."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiosqlite  # type: ignore
import discord  # type: ignore

from core.utils import get_mod_role, obsidian_embed
from database import DB_PATH, get_guild_setting, get_log_channel_id, get_quieter_mode, now_utc, set_guild_setting

logger = logging.getLogger(__name__)


async def run_ticket_sla_breach_cycle(bot: discord.Client) -> None:
    """Ping mod channel when open tickets lack first response past SLA."""
    from core.utils import get_mod_role
    from database import get_log_channel_id

    for guild in bot.guilds:
        try:
            sla_raw = await get_guild_setting(guild.id, "ticket_sla_hours")
            sla_h = int(sla_raw) if sla_raw and str(sla_raw).isdigit() else 4
            cutoff = (now_utc() - timedelta(hours=sla_h)).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT ticket_id, subject, channel_id FROM tickets
                    WHERE guild_id=? AND status='open'
                      AND (first_response_at IS NULL OR first_response_at='')
                      AND created_at < ?
                    LIMIT 5
                    """,
                    (guild.id, cutoff),
                )
                rows = await cur.fetchall()
            if not rows:
                continue
            ch_id = await get_log_channel_id(guild.id, "tickets") or await get_guild_setting(guild.id, "ticket_log_channel_id")
            ch = guild.get_channel(int(ch_id)) if ch_id and str(ch_id).isdigit() else None
            if not isinstance(ch, discord.TextChannel):
                continue
            mod_role = await get_mod_role(guild)
            mention = mod_role.mention if mod_role else ""
            for ticket_id, subject, tch in rows:
                warn_key = f"ticket_sla_warn:{ticket_id}"
                if await get_guild_setting(guild.id, warn_key):
                    continue
                from core.safe_send import safe_channel_send

                await safe_channel_send(
                    ch,
                    content=mention,
                    embed=obsidian_embed(
                        "ΓÅ▒∩╕Å Ticket SLA breach",
                        f"**{ticket_id}** ΓÇö {subject[:80]}\nNo first response in **{sla_h}h**.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                )
                await set_guild_setting(guild.id, warn_key, "1")
        except Exception:
            continue

async def run_stale_ticket_reminder_cycle(bot: discord.Client) -> None:
    """Remind staff about idle tickets; auto-close if still idle after warning."""
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

