"""User profile command showing comprehensive user statistics."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod, format_timestamp_readable, EMBED_FOOTER_DEFAULT
from database import (
    DB_PATH, now_utc, get_user_balance, get_user_xp, 
    calculate_level, xp_for_next_level
)
import aiosqlite


async def get_user_profile_data(guild_id: int, user_id: int) -> dict:
    """Get comprehensive user profile data."""
    data = {
        "balance": 0,
        "total_earned": 0,
        "xp": 0,
        "level": 0,
        "total_xp": 0,
        "messages_sent": 0,
        "voice_minutes": 0,
        "commands_used": 0,
        "events_attended": 0,
        "weekly_score": 0,
        "monthly_score": 0,
        "last_activity": None,
        "achievements": [],
        "warnings": 0,
        "reputation": 0,
        "daily_streak": 0,
        "join_date": None,
        "applications": {"total": 0, "approved": 0, "pending": 0},
        "suggestions": {"total": 0, "accepted": 0},
        "tickets": {"total": 0, "open": 0},
        "complaints": {"total": 0, "open": 0},
        "title": None,
        "equipped_badge": None,  # tuple (emoji, name)
    }
    
    g, u = guild_id, user_id
    async with aiosqlite.connect(DB_PATH) as db:
        # Query 1: Main stats via LEFT JOINs (single scan instead of 17 scalar subqueries)
        cur = await db.execute("""
            SELECT ub.balance, ub.total_earned, ux.xp, ux.level, ux.total_xp,
                   ast.messages_sent, ast.voice_minutes, ast.commands_used, ast.events_attended,
                   ast.weekly_score, ast.monthly_score, ast.last_activity_date,
                   (SELECT COUNT(*) FROM achievements WHERE guild_id=? AND user_id=?),
                   (SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?),
                   COALESCE(rp.reputation_points, 0), ut.title, dc.streak_days
            FROM (SELECT ? AS g, ? AS u) p
            LEFT JOIN user_balances ub ON ub.guild_id=p.g AND ub.user_id=p.u
            LEFT JOIN user_xp ux ON ux.guild_id=p.g AND ux.user_id=p.u
            LEFT JOIN activity_stats ast ON ast.guild_id=p.g AND ast.user_id=p.u
            LEFT JOIN reputation rp ON rp.guild_id=p.g AND rp.user_id=p.u
            LEFT JOIN user_titles ut ON ut.guild_id=p.g AND ut.user_id=p.u
            LEFT JOIN daily_claims dc ON dc.guild_id=p.g AND dc.user_id=p.u
        """, (g, u, g, u))
        row = await cur.fetchone()
        if row:
            data["balance"] = row[0] or 0
            data["total_earned"] = row[1] or 0
            data["xp"] = row[2] or 0
            data["level"] = row[3] or 0
            data["total_xp"] = row[4] or 0
            data["messages_sent"] = row[5] or 0
            data["voice_minutes"] = row[6] or 0
            data["commands_used"] = row[7] or 0
            data["events_attended"] = row[8] or 0
            data["weekly_score"] = row[9] or 0
            data["monthly_score"] = row[10] or 0
            data["last_activity"] = row[11]
            data["achievements_count"] = row[12] or 0
            data["warnings"] = row[13] or 0
            data["reputation"] = row[14] or 0
            data["title"] = row[15] if row[15] else None
            data["daily_streak"] = row[16] or 0

        # Query 2: Recent achievements + badge + pet + apps/suggestions/tickets/complaints (parallel fetches in one connection)
        cur = await db.execute("""
            SELECT a.achievement_id, a.unlocked_at, ad.name, ad.description
            FROM achievements a
            LEFT JOIN achievement_definitions ad ON a.achievement_id = ad.achievement_id
            WHERE a.guild_id=? AND a.user_id=?
            ORDER BY a.unlocked_at DESC LIMIT 5
        """, (g, u))
        data["achievements"] = await cur.fetchall()

        cur = await db.execute("""
            SELECT bd.icon_emoji, bd.name FROM user_badges ub
            LEFT JOIN badge_definitions bd ON ub.badge_id = bd.badge_id
            WHERE ub.guild_id=? AND ub.user_id=? AND ub.is_equipped=1
            ORDER BY ub.unlocked_at DESC LIMIT 1
        """, (g, u))
        brow = await cur.fetchone()
        if brow:
            data["equipped_badge"] = (brow[0], brow[1])

        cur = await db.execute("""
            SELECT ubs.slot, bd.icon_emoji, bd.name
            FROM user_badge_showcase ubs
            LEFT JOIN badge_definitions bd ON ubs.badge_id = bd.badge_id
            WHERE ubs.guild_id=? AND ubs.user_id=?
            ORDER BY ubs.slot
        """, (g, u))
        data["showcase_badges"] = await cur.fetchall()

        cur = await db.execute("""
            SELECT pet_name, pet_type, hunger, happiness, last_fed_at, last_played_at, created_at
            FROM pets WHERE guild_id=? AND user_id=?
        """, (g, u))
        pet_row = await cur.fetchone()
        if pet_row:
            data["pet"] = {"name": pet_row[0], "type": pet_row[1], "hunger": pet_row[2], "happiness": pet_row[3],
                          "last_fed": pet_row[4], "last_played": pet_row[5], "created_at": pet_row[6]}
        else:
            data["pet"] = None

        # Query 4: Applications, suggestions, tickets, complaints
        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END),0)
            FROM applications WHERE guild_id=? AND user_id=?
        """, (g, u))
        row = await cur.fetchone()
        if row:
            data["applications"] = {"total": row[0] or 0, "approved": row[1] or 0, "pending": row[2] or 0}

        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN status IN ('APPROVED','IMPLEMENTED') THEN 1 ELSE 0 END),0)
            FROM suggestions WHERE guild_id=? AND user_id=?
        """, (g, u))
        row = await cur.fetchone()
        if row:
            data["suggestions"] = {"total": row[0] or 0, "accepted": row[1] or 0}

        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),0)
            FROM tickets WHERE guild_id=? AND user_id=?
        """, (g, u))
        row = await cur.fetchone()
        if row:
            data["tickets"] = {"total": row[0] or 0, "open": row[1] or 0}

        cur = await db.execute("""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END),0)
            FROM complaints WHERE guild_id=? AND user_id=?
        """, (g, u))
        row = await cur.fetchone()
        if row:
            data["complaints"] = {"total": row[0] or 0, "open": row[1] or 0}

    return data


def setup(bot, group=None):
    """Register the profile command."""
    command_decorator = group.command(name="profile", description="View your or another user's profile and statistics.") if group else bot.tree.command(name="profile", description="View your or another user's profile and statistics.")
    
    @command_decorator
    @app_commands.describe(user="The user to view the profile of (defaults to yourself)")
    async def profile(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """Display a comprehensive user profile."""
        await interaction.response.defer(ephemeral=False)
        
        target_user = user or interaction.user
        if not isinstance(target_user, discord.Member):
            return await interaction.followup.send("User not found in this server.", ephemeral=True)
        
        # Get profile data
        profile_data = await get_user_profile_data(interaction.guild.id, target_user.id)
        
        # Calculate XP progress
        from database import xp_for_level, xp_for_next_level
        from utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT
        current_level = profile_data["level"]
        current_xp = profile_data["xp"]
        xp_for_current = xp_for_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if current_level > 0 else 0
        xp_for_next = xp_for_next_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
        xp_needed = xp_for_next - current_xp
        xp_progress = current_xp - xp_for_current
        xp_range = xp_for_next - xp_for_current
        progress_percent = int((xp_progress / xp_range * 100)) if xp_range > 0 else 0
        
        # Format voice time
        voice_hours = profile_data["voice_minutes"] // 60
        voice_mins = profile_data["voice_minutes"] % 60
        voice_time = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"
        
        # Format join date (Discord timestamp for user's locale)
        join_date_str = "Unknown"
        if target_user.joined_at:
            join_date = target_user.joined_at.replace(tzinfo=timezone.utc)
            join_date_str = format_timestamp_readable(join_date, include_relative=True)
            join_date_ts = int(target_user.joined_at.timestamp())
        
        # Build embed
        fields = []
        
        # Pet section (if user has a pet)
        if profile_data.get("pet"):
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR
            pet = profile_data["pet"]
            hunger = _apply_decay(pet["hunger"], pet.get("last_fed"), pet.get("created_at"), HUNGER_DECAY_PER_HOUR)
            happiness = _apply_decay(pet["happiness"], pet.get("last_played"), pet.get("created_at"), HAPPINESS_DECAY_PER_HOUR)
            hunger_emoji = "🍽️" if hunger < 50 else "✅"
            happy_emoji = "😢" if happiness < 50 else "😊"
            fields.append((
                "🐾 Pet",
                f"**{pet['name']}** ({pet['type']})\n"
                f"Hunger: {hunger}/100 {hunger_emoji}\n"
                f"Happiness: {happiness}/100 {happy_emoji}\n"
                f"_Use `/economy pets feed` and `/economy pets play` to care for your pet._",
                True
            ))

        # Economy section
        if profile_data["balance"] > 0 or profile_data["total_earned"] > 0:
            fields.append((
                "💰 Economy",
                f"**Balance:** {profile_data['balance']:,} coins\n"
                f"**Total Earned:** {profile_data['total_earned']:,} coins\n"
                f"**Daily Streak:** {profile_data['daily_streak']} days",
                True
            ))
        
        # Leveling section
        if profile_data["level"] > 0 or profile_data["xp"] > 0:
            progress_bar = "█" * (progress_percent // 5) + "░" * (20 - (progress_percent // 5))
            fields.append((
                "📊 Leveling",
                f"**Level:** {profile_data['level']}\n"
                f"**XP:** {profile_data['xp']:,} / {xp_for_next:,}\n"
                f"**Progress:** {progress_bar} {progress_percent}%\n"
                f"**Total XP:** {profile_data['total_xp']:,}",
                True
            ))
        
        # Activity section
        fields.append((
            "📈 Activity",
            f"**Messages:** {profile_data['messages_sent']:,}\n"
            f"**Voice Time:** {voice_time}\n"
            f"**Commands Used:** {profile_data['commands_used']:,}\n"
            f"**Events Attended:** {profile_data['events_attended']}",
            True
        ))
        
        # Community section
        community_text = f"**Reputation:** {profile_data['reputation']:+}\n"
        if profile_data["applications"]["total"] > 0:
            community_text += f"**Applications:** {profile_data['applications']['total']} (✓{profile_data['applications']['approved']})\n"
        if profile_data["suggestions"]["total"] > 0:
            community_text += f"**Suggestions:** {profile_data['suggestions']['total']} (✓{profile_data['suggestions']['accepted']})\n"
        if profile_data["tickets"]["total"] > 0:
            community_text += f"**Tickets:** {profile_data['tickets']['total']}\n"
        if profile_data["complaints"]["total"] > 0:
            community_text += f"**Complaints:** {profile_data['complaints']['total']}"
        
        if community_text.strip() != "**Reputation:** 0":
            fields.append(("👥 Community", community_text, True))
        
        # Achievements section
        if profile_data["achievements_count"] > 0:
            achievements_text = f"**Total:** {profile_data['achievements_count']} unlocked\n\n"
            if profile_data["achievements"]:
                achievements_text += "**Recent:**\n"
                for ach_id, unlocked_at, name, desc in profile_data["achievements"][:3]:
                    ach_name = name or ach_id.replace("_", " ").title()
                    achievements_text += f"• {ach_name}\n"
            fields.append(("🏆 Achievements", achievements_text, True))
        
        # Moderation section (only if warnings > 0 or user is mod viewing)
        if profile_data["warnings"] > 0 or (is_mod(interaction.user) and target_user.id != interaction.user.id):
            mod_text = f"**Warnings:** {profile_data['warnings']}"
            fields.append(("🛡️ Moderation", mod_text, True))
        
        # Activity scores
        if profile_data["weekly_score"] > 0 or profile_data["monthly_score"] > 0:
            fields.append((
                "⭐ Activity Scores",
                f"**Weekly:** {profile_data['weekly_score']:,}\n"
                f"**Monthly:** {profile_data['monthly_score']:,}",
                True
            ))
        
        # Build description: Member since, title and badges prominent
        desc_parts = [f"Profile for {target_user.mention}"]
        if target_user.joined_at:
            desc_parts.append(f"\n**Member since:** {join_date_str}")
        if profile_data.get("title"):
            desc_parts.append(f"\n**Title:** {profile_data['title']}")
        if profile_data.get("equipped_badge"):
            emoji, name = profile_data["equipped_badge"]
            badge_emoji = emoji or "🏆"
            badge_name = name or "Badge"
            desc_parts.append(f"\n**Equipped Badge:** {badge_emoji} {badge_name}")
        if profile_data.get("showcase_badges"):
            showcase = profile_data["showcase_badges"]
            parts = [f"{(e or '🏆')} {n or 'Badge'}" for _, e, n in showcase[:5]]
            desc_parts.append(f"\n**Showcase:** {' '.join(parts)}")
        if target_user.id == interaction.user.id:
            desc_parts.append("\n_This is your profile!_")
        desc = "".join(desc_parts)
        
        embed = obsidian_embed(
            f"👤 {target_user.display_name}'s Profile",
            desc,
            color=target_user.color if target_user.color.value != 0 else discord.Color.blurple(),
            author=target_user,
            fields=fields,
            client=interaction.client,
        )

        # Ephemeral when viewing own profile (private)
        ephemeral = target_user.id == interaction.user.id

        # Consistent footer
        footer_parts = [EMBED_FOOTER_DEFAULT]
        if profile_data["last_activity"]:
            try:
                last_activity = datetime.fromisoformat(profile_data["last_activity"])
                days_ago = (now_utc() - last_activity.replace(tzinfo=timezone.utc)).days
                footer_parts.append(f"Last active: {days_ago}d ago")
            except Exception:
                pass
        if profile_data["achievements_count"] > 0:
            footer_parts.append("/achievements for full list")
        embed.set_footer(text=" • ".join(footer_parts))
        embed.set_thumbnail(url=target_user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
