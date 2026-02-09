"""User profile command showing comprehensive user statistics."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone

from utils import obsidian_embed, is_mod
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Economy data
        cur = await db.execute("""
            SELECT balance, total_earned FROM user_balances
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["balance"] = row[0] or 0
            data["total_earned"] = row[1] or 0
        
        # XP data
        cur = await db.execute("""
            SELECT xp, level, total_xp FROM user_xp
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["xp"] = row[0] or 0
            data["level"] = row[1] or 0
            data["total_xp"] = row[2] or 0
        
        # Activity stats
        cur = await db.execute("""
            SELECT messages_sent, voice_minutes, commands_used, events_attended,
                   weekly_score, monthly_score, last_activity_date
            FROM activity_stats
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["messages_sent"] = row[0] or 0
            data["voice_minutes"] = row[1] or 0
            data["commands_used"] = row[2] or 0
            data["events_attended"] = row[3] or 0
            data["weekly_score"] = row[4] or 0
            data["monthly_score"] = row[5] or 0
            data["last_activity"] = row[6]
        
        # Achievements
        cur = await db.execute("""
            SELECT COUNT(*) FROM achievements
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        data["achievements_count"] = row[0] if row else 0
        
        # Get recent achievements
        cur = await db.execute("""
            SELECT a.achievement_id, a.unlocked_at, ad.name, ad.description
            FROM achievements a
            LEFT JOIN achievement_definitions ad ON a.achievement_id = ad.achievement_id
            WHERE a.guild_id=? AND a.user_id=?
            ORDER BY a.unlocked_at DESC
            LIMIT 5
        """, (guild_id, user_id))
        data["achievements"] = await cur.fetchall()
        
        # Warnings
        cur = await db.execute("""
            SELECT COUNT(*) FROM warnings
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        data["warnings"] = row[0] if row else 0
        
        # Reputation
        cur = await db.execute("""
            SELECT reputation_points FROM reputation
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        data["reputation"] = row[0] if row else 0

        # Title (optional)
        cur = await db.execute("""
            SELECT title FROM user_titles
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        data["title"] = row[0] if row and row[0] else None

        # Equipped badge (optional)
        cur = await db.execute("""
            SELECT bd.icon_emoji, bd.name
            FROM user_badges ub
            LEFT JOIN badge_definitions bd ON ub.badge_id = bd.badge_id
            WHERE ub.guild_id=? AND ub.user_id=? AND ub.is_equipped=1
            ORDER BY ub.unlocked_at DESC
            LIMIT 1
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["equipped_badge"] = (row[0], row[1])
        
        # Daily streak
        cur = await db.execute("""
            SELECT streak_days FROM daily_claims
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        data["daily_streak"] = row[0] if row else 0
        
        # Applications
        cur = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) as pending
            FROM applications
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["applications"]["total"] = row[0] or 0
            data["applications"]["approved"] = row[1] or 0
            data["applications"]["pending"] = row[2] or 0
        
        # Suggestions
        cur = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status='ACCEPTED' THEN 1 ELSE 0 END) as accepted
            FROM suggestions
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["suggestions"]["total"] = row[0] or 0
            data["suggestions"]["accepted"] = row[1] or 0
        
        # Pet (for pet status in profile)
        cur = await db.execute("""
            SELECT p.pet_name, p.pet_type, p.hunger, p.happiness, p.last_fed_at, p.last_played_at, p.created_at
            FROM pets p
            WHERE p.guild_id=? AND p.user_id=?
        """, (guild_id, user_id))
        pet_row = await cur.fetchone()
        if pet_row:
            data["pet"] = {
                "name": pet_row[0],
                "type": pet_row[1],
                "hunger": pet_row[2],
                "happiness": pet_row[3],
                "last_fed": pet_row[4],
                "last_played": pet_row[5],
                "created_at": pet_row[6],
            }
        else:
            data["pet"] = None

        # Tickets
        cur = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) as open
            FROM tickets
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["tickets"]["total"] = row[0] or 0
            data["tickets"]["open"] = row[1] or 0
        
        # Complaints
        cur = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open
            FROM complaints
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if row:
            data["complaints"]["total"] = row[0] or 0
            data["complaints"]["open"] = row[1] or 0
    
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
        
        # Format join date
        join_date_str = "Unknown"
        if target_user.joined_at:
            join_date = target_user.joined_at.replace(tzinfo=timezone.utc)
            days_in_server = (now_utc() - join_date).days
            join_date_str = f"{days_in_server} days ago"
        
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
                f"_Use `/pet_feed` and `/pet_play` to care for your pet._",
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
            if is_mod(interaction.user) and target_user.id != interaction.user.id:
                mod_text += f"\n**Member Since:** {join_date_str}"
            fields.append(("🛡️ Moderation", mod_text, True))
        
        # Activity scores
        if profile_data["weekly_score"] > 0 or profile_data["monthly_score"] > 0:
            fields.append((
                "⭐ Activity Scores",
                f"**Weekly:** {profile_data['weekly_score']:,}\n"
                f"**Monthly:** {profile_data['monthly_score']:,}",
                True
            ))
        
        # Build description
        desc = f"Comprehensive profile for {target_user.mention}\n"
        if profile_data.get("title"):
            desc += f"\n**Title:** {profile_data['title']}"
        if profile_data.get("equipped_badge"):
            emoji, name = profile_data["equipped_badge"]
            badge_emoji = emoji or "🏆"
            badge_name = name or "Badge"
            desc += f"\n**Equipped Badge:** {badge_emoji} {badge_name}"
        if target_user.id == interaction.user.id:
            desc += "\n*This is your profile!*"
        
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

        # Add footer
        footer_text = f"User ID: {target_user.id}"
        if profile_data["last_activity"]:
            try:
                last_activity = datetime.fromisoformat(profile_data["last_activity"])
                days_ago = (now_utc() - last_activity.replace(tzinfo=timezone.utc)).days
                footer_text += f" • Last active: {days_ago} day(s) ago"
            except:
                pass
        embed.set_footer(text=footer_text)
        embed.set_thumbnail(url=target_user.display_avatar.url)

        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
