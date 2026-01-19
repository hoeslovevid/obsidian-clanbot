"""
Event handlers for the bot.
This module contains all Discord event handlers to keep bot.py clean.
"""
import logging
import discord
from datetime import datetime, timezone
import aiosqlite

from utils import obsidian_embed, is_mod, get_mod_role
from database import DB_PATH, now_utc, get_guild_setting, get_user_balance, add_coins, get_user_xp, add_xp, calculate_level
from channels import resolve_channel_id, delete_temp_vc_and_panel, resolve_temp_vc_category
from modals import ComplaintModal, RequestInfoModal
from views import ComplaintPanel, ComplaintModView

logger = logging.getLogger(__name__)

# Import config from bot.py (will be passed in)
def setup_events(bot, config):
    """Set up all event handlers."""
    
    @bot.event
    async def on_message(message: discord.Message):
        """Handle messages for economy, XP, and auto-moderation."""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Process commands first
        await bot.process_commands(message)
        
        # Economy and XP system
        if message.guild and not message.content.startswith(bot.command_prefix):
            if config.get("ECONOMY_ENABLED", True):
                # Check cooldown
                from database import get_last_message_time, update_last_message_time
                last_time = await get_last_message_time(message.guild.id, message.author.id)
                if last_time:
                    try:
                        last_dt = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                        time_diff = (now_utc() - last_dt).total_seconds()
                        if time_diff < config.get("MESSAGE_COOLDOWN_SECONDS", 60):
                            return  # Still on cooldown
                    except Exception:
                        pass
                
                # Award coins
                coins = config.get("COINS_PER_MESSAGE", 5)
                await add_coins(message.guild.id, message.author.id, coins)
                await update_last_message_time(message.guild.id, message.author.id, now_utc().isoformat())
            
            if config.get("XP_ENABLED", True):
                # Award XP
                xp = config.get("XP_PER_MESSAGE", 1)
                await add_xp(message.guild.id, message.author.id, xp)
        
        # Auto-moderation
        if message.guild:
            from bot import check_auto_mod
            should_delete = await check_auto_mod(message)
            if should_delete:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
    
    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice channel joins/leaves for economy and temp VC creation."""
        if not member.guild:
            return
        
        now = now_utc()
        
        # Voice activity tracking for economy/XP
        if after.channel and isinstance(after.channel, discord.VoiceChannel):
            if not (after.self_mute or after.self_deaf):
                async with aiosqlite.connect(DB_PATH) as db:
                    # First, get existing total_minutes if any
                    cur = await db.execute("""
                        SELECT total_minutes FROM voice_activity
                        WHERE guild_id=? AND user_id=? AND channel_id=?
                    """, (member.guild.id, member.id, after.channel.id))
                    row = await cur.fetchone()
                    existing_minutes = row[0] if row else 0
                    
                    # Now insert or replace with preserved total_minutes
                    await db.execute("""
                        INSERT OR REPLACE INTO voice_activity (guild_id, user_id, channel_id, joined_at, last_reward_at, total_minutes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (member.guild.id, member.id, after.channel.id, now.isoformat(), None, existing_minutes))
                    await db.commit()
        
        # Join-to-create logic
        if not after.channel:
            return

        create_id_s = await get_guild_setting(member.guild.id, "create_vc_channel_id")
        if not (create_id_s and create_id_s.isdigit()):
            return

        create_id = int(create_id_s)
        if after.channel.id != create_id:
            # Track last non-empty times for cleanup
            for ch in (before.channel, after.channel):
                if ch and isinstance(ch, discord.VoiceChannel):
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT 1 FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (member.guild.id, ch.id),
                        )
                        exists = await cur.fetchone()
                        if exists and len(ch.members) > 0:
                            await db.execute(
                                "UPDATE temp_vcs SET last_nonempty_at=? WHERE guild_id=? AND channel_id=?",
                                (now_utc().isoformat(), member.guild.id, ch.id),
                            )
                            await db.commit()
            return

        guild = member.guild
        category = await resolve_temp_vc_category(guild)
        mod_role = get_mod_role(guild)

        # Create VC
        vc_name = f"{member.display_name}'s Cell"
        try:
            vc = await guild.create_voice_channel(
                vc_name,
                category=category,
                reason=f"Join-to-create VC for {member.display_name}",
            )
        except discord.Forbidden:
            logger.error(f"[vc] No permission to create VC in {guild.name}")
            return

        # Store in DB
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO temp_vcs(guild_id,channel_id,owner_id,created_at,last_nonempty_at) VALUES(?,?,?,?,?)",
                (guild.id, vc.id, member.id, now_utc().isoformat(), now_utc().isoformat()),
            )
            await db.commit()

        # Move user
        try:
            await member.move_to(vc, reason="Join-to-create VC")
        except discord.Forbidden:
            logger.warning(f"[vc] Could not move {member} to new VC")

        # Post panel
        from bot import post_vc_panel
        await post_vc_panel(guild, vc, member)
    
    @bot.event
    async def on_member_join(member: discord.Member):
        """Handle member joins for welcome messages and milestones."""
        if not member.guild:
            return
        
        # Welcome message
        from database import get_guild_setting
        welcome_channel_id_str = await get_guild_setting(member.guild.id, "welcome_channel_id")
        if welcome_channel_id_str and welcome_channel_id_str.isdigit():
            welcome_channel_id = int(welcome_channel_id_str)
            channel = member.guild.get_channel(welcome_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                welcome_message = await get_guild_setting(member.guild.id, "welcome_message")
                if welcome_message:
                    try:
                        await channel.send(welcome_message.replace("{user}", member.mention).replace("{server}", member.guild.name))
                    except Exception as e:
                        logger.error(f"Error sending welcome message: {e}")
        
        # Check milestones
        from database import check_and_record_milestone
        await check_and_record_milestone(member.guild.id, member.id, "join_anniversary", now_utc().isoformat())
    
    @bot.event
    async def on_member_remove(member: discord.Member):
        """Handle member leaves for logging."""
        if not member.guild:
            return
        
        # Log member leave
        from database import get_log_channel
        log_channel_id = await get_log_channel(member.guild.id, "member_leave")
        if log_channel_id:
            channel = member.guild.get_channel(log_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                embed = obsidian_embed(
                    "👋 Member Left",
                    f"**{member}** ({member.id}) left the server.",
                    color=discord.Color.orange(),
                    client=bot,
                )
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass
    
    @bot.event
    async def on_message_delete(message: discord.Message):
        """Log deleted messages for snipe command."""
        if not message.guild or message.author.bot:
            return
        
        from database import log_deleted_message
        await log_deleted_message(
            message.guild.id,
            message.channel.id,
            message.author.id,
            message.content or "",
            message.id,
            now_utc().isoformat()
        )
    
    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message):
        """Log edited messages."""
        if not before.guild or before.author.bot or before.content == after.content:
            return
        
        from database import log_edited_message
        await log_edited_message(
            before.guild.id,
            before.channel.id,
            before.author.id,
            before.content or "",
            after.content or "",
            before.id,
            now_utc().isoformat()
        )
    
    @bot.event
    async def on_member_ban(guild: discord.Guild, user: discord.User):
        """Log member bans."""
        from database import get_log_channel
        log_channel_id = await get_log_channel(guild.id, "member_ban")
        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                embed = obsidian_embed(
                    "🔨 Member Banned",
                    f"**{user}** ({user.id}) was banned from the server.",
                    color=discord.Color.red(),
                    client=bot,
                )
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass
    
    @bot.event
    async def on_member_update(before: discord.Member, after: discord.Member):
        """Log role changes."""
        if before.roles != after.roles:
            from database import get_log_channel
            log_channel_id = await get_log_channel(after.guild.id, "role_change")
            if log_channel_id:
                channel = after.guild.get_channel(log_channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    added = [r for r in after.roles if r not in before.roles]
                    removed = [r for r in before.roles if r not in after.roles]
                    
                    if added or removed:
                        desc = ""
                        if added:
                            desc += f"**Added:** {', '.join([r.mention for r in added])}\n"
                        if removed:
                            desc += f"**Removed:** {', '.join([r.mention for r in removed])}\n"
                        desc += f"**Member:** {after.mention}"
                        
                        embed = obsidian_embed(
                            "🔀 Role Update",
                            desc,
                            color=discord.Color.blue(),
                            client=bot,
                        )
                        try:
                            await channel.send(embed=embed)
                        except Exception:
                            pass
