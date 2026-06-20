"""Member join/leave handlers (extracted from bot/app.py)."""
from __future__ import annotations

import logging
from datetime import timezone

import discord  # type: ignore

from core.db import open_db
from core.utils import obsidian_embed
from database import get_guild_setting, now_utc

logger = logging.getLogger(__name__)

_achievement_definitions_initialized = False


async def handle_member_join(bot: discord.Client, member: discord.Member) -> None:
    """Send welcome message when a member joins."""
    # Check for join anniversary milestones (check existing join date)
    global _achievement_definitions_initialized  # module cache
    from database import check_and_record_milestone, check_and_unlock_achievement, initialize_achievement_definitions, initialize_badge_definitions, initialize_title_definitions
    
    # Only initialize once (cached)
    if not _achievement_definitions_initialized:
        await initialize_achievement_definitions()
        await initialize_badge_definitions()
        await initialize_title_definitions()
        _achievement_definitions_initialized = True

    # Get member's join date
    join_date = member.joined_at or now_utc()
    years_in_server = (now_utc() - join_date.replace(tzinfo=timezone.utc)).days // 365
    
    # Check anniversary milestones
    if years_in_server >= 1:
        milestone_achieved = await check_and_record_milestone(
            member.guild.id, member.id, "join_anniversary", years_in_server
        )
        if milestone_achieved and years_in_server <= 2:  # Only for 1-2 year anniversaries
            achievement_id = f"join_anniversary_{years_in_server}"
            await check_and_unlock_achievement(member.guild.id, member.id, achievement_id, bot)
    
    # Raid protection - record join
    try:
        from core.member_journey import record_member_join

        await record_member_join(member.guild.id, member.id)
    except Exception as e:
        logger.debug(f"[member_journey] join log failed: {e}")

    try:
        from commands.moderation.raid_protection import record_join, check_raid_condition, trigger_raid_protection
        account_age = None
        if member.created_at:
            account_age = (now_utc() - member.created_at.replace(tzinfo=timezone.utc)).days
        await record_join(member.guild.id, member.id, account_age)
        
        # Check if raid conditions are met
        is_raid, join_count = await check_raid_condition(member.guild)
        if is_raid:
            await trigger_raid_protection(member.guild, join_count)
    except Exception as e:
        logger.error(f"[raid_protection] Error in raid protection: {e}")
    
    # Server milestones - check member count milestones
    try:
        from commands.general.milestones import check_and_celebrate_milestone
        member_count = member.guild.member_count
        # Check for round number milestones (100, 500, 1000, etc.)
        if member_count is not None and (
            member_count % 100 == 0
            or member_count in [50, 250, 500, 1000, 2500, 5000, 10000]
        ):
            await check_and_celebrate_milestone(member.guild, "member_count", member_count, bot=bot)
    except Exception as e:
        logger.error(f"[milestones] Error checking member count milestone: {e}")
    
    async with open_db() as db:
        cur = await db.execute("""
            SELECT channel_id, message, enabled FROM welcome_settings
            WHERE guild_id = ? AND enabled = 1
        """, (member.guild.id,))
        row = await cur.fetchone()
    
    if not row or not row[0]:  # No channel set or disabled
        return
    
    channel_id, message_template, enabled = row
    if not enabled:
        return
    
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    # Optional: send welcome DM if configured
    try:
        dm_enabled = await get_guild_setting(member.guild.id, "welcome_dm_enabled")
        dm_msg = await get_guild_setting(member.guild.id, "welcome_dm_message")
        if dm_enabled == "1" and dm_msg:
            dm_text = dm_msg.replace("{user}", str(member)).replace("{server}", member.guild.name)
            dm_text = dm_text.replace("{member_count}", str(member.guild.member_count or 0))
            from core.safe_send import safe_dm
            await safe_dm(member, content=dm_text[:2000])
    except Exception:
        pass  # User may have DMs disabled

    # Default short welcome DM when no custom welcome_dm is configured.
    try:
        default_off = await get_guild_setting(member.guild.id, "welcome_dm_default_off")
        custom_dm = await get_guild_setting(member.guild.id, "welcome_dm_enabled")
        if default_off != "1" and custom_dm != "1":
            short = (
                f"Welcome to **{member.guild.name}**! "
                "Try `/start` or `/menu` for quick actions, `/help` for commands, and `/preferences` to set your timezone."
            )
            from core.safe_send import safe_dm
            await safe_dm(member, content=short[:2000])
    except Exception:
        pass

    # Item 8: first-run onboarding DM (additive — runs alongside the welcome DM above).
    try:
        from commands.general.onboarding import maybe_send_onboarding_on_join
        await maybe_send_onboarding_on_join(member, bot)
    except Exception as e:
        logger.debug(f"[onboarding] join hook failed: {e}")
    
    # Format message
    formatted_message = message_template.replace("{user}", member.mention)
    formatted_message = formatted_message.replace("{server}", member.guild.name)
    formatted_message = formatted_message.replace("{member_count}", str(member.guild.member_count or 0))
    
    try:
        await channel.send(formatted_message)
        card_off = await get_guild_setting(member.guild.id, "welcome_card_off")
        if card_off != "1":
            from core.welcome_card import WelcomeCardView, welcome_card_embed

            view = WelcomeCardView(member.guild.id)
            bot.add_view(view)
            await channel.send(
                embed=welcome_card_embed(member, client=bot),
                view=view,
            )
    except Exception as e:
        logger.error(f"[welcome] Error sending welcome message: {e}")




async def handle_member_remove(bot: discord.Client, member: discord.Member) -> None:
    """Send leave message and log kicks."""
    # Check if it was a kick (audit log)
    was_kicked = False
    try:
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
            if entry.target and entry.target.id == member.id:
                was_kicked = True
                # Log kick
                async with open_db() as db:
                    cur = await db.execute("""
                        SELECT channel_id FROM log_channels
                        WHERE guild_id=? AND log_type='member_kick' AND enabled=1
                    """, (member.guild.id,))
                    row = await cur.fetchone()
                
                if row:
                    log_channel = member.guild.get_channel(row[0])
                    if isinstance(log_channel, discord.TextChannel):
                        try:
                            reason = entry.reason or "No reason provided"
                            embed = obsidian_embed(
                                "👢 Member Kicked",
                                f"**User:** {member.mention} ({member})\n"
                                f"**User ID:** {member.id}\n"
                                f"**Reason:** {reason}",
                                color=discord.Color.orange(),
                                client=bot,
                            )
                            await log_channel.send(embed=embed)
                        except Exception as e:
                            logger.error(f"[logging] Error logging member kick: {e}")
                break
    except Exception:
        pass
    
    # Original leave message code
    async with open_db() as db:
        cur = await db.execute("""
            SELECT channel_id, message, enabled FROM leave_settings
            WHERE guild_id = ? AND enabled = 1
        """, (member.guild.id,))
        row = await cur.fetchone()
    
    if not row or not row[0]:  # No channel set or disabled
        return
    
    channel_id, message_template, enabled = row
    if not enabled:
        return
    
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    from core.leave_messages import format_leave_message

    formatted_message = format_leave_message(member, message_template)

    try:
        await channel.send(formatted_message)
    except Exception as e:
        logger.error(f"[leave] Error sending leave message: {e}")


