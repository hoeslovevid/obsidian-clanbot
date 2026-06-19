"""User profile command showing comprehensive user statistics."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone

from core.embed_footers import footer_for
from core.utils import obsidian_embed, is_mod, format_timestamp_readable, EMBED_FOOTER_DEFAULT, render_bar, EMBED_COLORS
from database import (
    DB_PATH, now_utc, get_user_balance, get_user_xp,
    calculate_level, xp_for_next_level, get_guild_setting,
    get_linked_steam_id,
)
import aiosqlite


class BioModal(discord.ui.Modal, title="Set Your Profile Bio"):
    bio = discord.ui.TextInput(
        label="Bio",
        placeholder="Write a short bio about yourself (max 150 chars)…",
        max_length=150,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
        from database import set_guild_setting
        bio_text = self.bio.value.strip()
        await set_guild_setting(interaction.guild.id, f"user_bio:{interaction.user.id}", bio_text)
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Bio Updated",
                f"> {bio_text}" if bio_text else "Your bio has been cleared.",
                category="general",
                client=interaction.client,
            ),
            ephemeral=True,
        )


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
        "bio": None,
        "ign_verified": False,
        "warframe_ign": None,
        "steam_playtime": None,
        "goal_multiplier": None,
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
        """, (g, u, g, u, g, u))
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

        cur = await db.execute("SELECT COUNT(*) FROM achievement_definitions")
        data["achievements_total"] = int((await cur.fetchone())[0] or 0)

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

        # Bio
        cur = await db.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (g, f"user_bio:{u}"),
        )
        bio_row = await cur.fetchone()
        data["bio"] = bio_row[0].strip() if bio_row and bio_row[0] else None

        cur = await db.execute(
            "SELECT ign, status FROM ign_verifications WHERE guild_id=? AND user_id=?",
            (g, u),
        )
        ign_row = await cur.fetchone()
        if ign_row:
            data["warframe_ign"] = ign_row[0]
            data["ign_verified"] = str(ign_row[1]).lower() == "verified"

    steam_id = await get_linked_steam_id(g, u)
    if steam_id:
        try:
            from api.warframe_api import fetch_steam_warframe_playtime
            data["steam_playtime"] = await fetch_steam_warframe_playtime(steam_id)
        except Exception:
            pass

    xp_until = await get_guild_setting(g, "xp_multiplier_until")
    coins_until = await get_guild_setting(g, "coins_multiplier_until")
    now_ts = int(now_utc().timestamp())
    mult_parts = []
    if xp_until and str(xp_until).isdigit() and int(xp_until) > now_ts:
        mult_parts.append("XP boost live")
    if coins_until and str(coins_until).isdigit() and int(coins_until) > now_ts:
        mult_parts.append("Coin boost live")
    if mult_parts:
        data["goal_multiplier"] = " · ".join(mult_parts)

    return data


async def build_profile_embed(
    guild: discord.Guild,
    target_user: discord.Member,
    profile_data: dict,
    *,
    viewer: discord.abc.User,
    client,
) -> discord.Embed:
    """Shared profile card — used by /profile and View Profile context menu."""
    from database import xp_for_level, xp_for_next_level
    from core.utils import XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT, now_utc

    is_self = isinstance(viewer, discord.Member) and viewer.id == target_user.id
    current_level = profile_data["level"]
    current_xp = profile_data["xp"]
    xp_for_current = xp_for_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT) if current_level > 0 else 0
    xp_for_next = xp_for_next_level(current_level, XP_LEVEL_MULTIPLIER, XP_LEVEL_EXPONENT)
    xp_progress = current_xp - xp_for_current
    xp_range = xp_for_next - xp_for_current
    progress_percent = int((xp_progress / xp_range * 100)) if xp_range > 0 else 0

    voice_hours = profile_data["voice_minutes"] // 60
    voice_mins = profile_data["voice_minutes"] % 60
    voice_time = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"

    fields = []

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
            f"_Use `/pets feed` and `/pets play` to care for your pet._",
            True,
        ))

    if profile_data["balance"] > 0 or profile_data["total_earned"] > 0:
        fields.append((
            "💰 Economy",
            f"**Balance:** {profile_data['balance']:,} coins\n"
            f"**Total Earned:** {profile_data['total_earned']:,} coins\n"
            f"**Daily Streak:** {profile_data['daily_streak']} days",
            True,
        ))

    if profile_data["level"] > 0 or profile_data["xp"] > 0:
        fields.append((
            "📊 Leveling",
            f"**Level:** {profile_data['level']}\n"
            f"**XP:** {profile_data['xp']:,} / {xp_for_next:,}\n"
            f"{render_bar(progress_percent)}\n"
            f"**Total XP:** {profile_data['total_xp']:,}",
            True,
        ))

    fields.append((
        "📈 Activity",
        f"**Messages:** {profile_data['messages_sent']:,}\n"
        f"**Voice Time:** {voice_time}\n"
        f"**Commands Used:** {profile_data['commands_used']:,}\n"
        f"**Events Attended:** {profile_data['events_attended']}",
        True,
    ))

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

    if profile_data.get("achievements_count", 0) > 0 or profile_data.get("achievements_total"):
        total_def = profile_data.get("achievements_total") or profile_data["achievements_count"]
        achievements_text = f"**{profile_data['achievements_count']}/{total_def}** unlocked\n\n"
        if profile_data["achievements"]:
            achievements_text += "**Recent:**\n"
            for ach_id, unlocked_at, name, desc in profile_data["achievements"][:3]:
                ach_name = name or ach_id.replace("_", " ").title()
                achievements_text += f"• {ach_name}\n"
        fields.append(("🏆 Achievements", achievements_text, True))

    if is_self:
        try:
            from core.achievement_nudges import get_achievement_nudges
            nudges = await get_achievement_nudges(guild.id, target_user.id, profile_data)
            if nudges:
                fields.append((
                    "🎯 Almost there",
                    "\n".join(f"• {n}" for n in nudges),
                    False,
                ))
        except Exception:
            pass

    if profile_data["warnings"] > 0 or (is_mod(viewer) and target_user.id != viewer.id):
        fields.append(("🛡️ Moderation", f"**Warnings:** {profile_data['warnings']}", True))

    if profile_data["weekly_score"] > 0 or profile_data["monthly_score"] > 0:
        fields.append((
            "⭐ Activity Scores",
            f"**Weekly:** {profile_data['weekly_score']:,}\n"
            f"**Monthly:** {profile_data['monthly_score']:,}",
            True,
        ))

    desc_lines = []
    identity_parts = []
    if target_user.joined_at:
        join_date_str = format_timestamp_readable(target_user.joined_at, include_relative=True)
        identity_parts.append(f"📅 Member since {join_date_str}")
    if profile_data.get("title"):
        identity_parts.append(f"🏷️ {profile_data['title']}")
    if identity_parts:
        desc_lines.append("\n".join(f"> {p}" for p in identity_parts))

    if profile_data.get("bio"):
        desc_lines.append(f"*{profile_data['bio']}*")
    if profile_data.get("ign_verified") and profile_data.get("warframe_ign"):
        desc_lines.append(f"✅ **Verified IGN:** {profile_data['warframe_ign']}")
    elif profile_data.get("warframe_ign"):
        desc_lines.append(f"🎮 IGN: {profile_data['warframe_ign']}")
    if profile_data.get("steam_playtime") is not None:
        desc_lines.append(f"🎮 Warframe: **{profile_data['steam_playtime']:,}h** on Steam")
    if profile_data.get("goal_multiplier"):
        desc_lines.append(f"🎯 {profile_data['goal_multiplier']}")
    if profile_data.get("equipped_badge"):
        emoji, name = profile_data["equipped_badge"]
        desc_lines.append(f"{emoji or '🏆'} **{name or 'Badge'}**")
    if profile_data.get("showcase_badges"):
        showcase = profile_data["showcase_badges"]
        parts = [f"{(e or '🏆')}" for _, e, n in showcase[:5]]
        desc_lines.append(f"Showcase: {'  '.join(parts)}")
    if is_self:
        desc_lines.append("-# This is your profile  ·  Use /general set_bio to add a bio")

    desc = "\n".join(desc_lines)

    footer_parts = []
    if profile_data["last_activity"]:
        try:
            last_activity = datetime.fromisoformat(profile_data["last_activity"])
            days_ago = (now_utc() - last_activity.replace(tzinfo=timezone.utc)).days
            footer_parts.append(f"Last active {days_ago}d ago")
        except Exception:
            pass
    if profile_data["achievements_count"] > 0:
        footer_parts.append("/achievements for full list")
    footer_text = " · ".join(footer_parts) if footer_parts else footer_for("profile")

    if profile_data.get("pet"):
        from commands.economy.pets import get_pet_emoji
        _pet = profile_data["pet"]
        _pname = _pet.get("name") or _pet.get("type") or "Pet"
        footer_text = f"{get_pet_emoji(_pet.get('type'))} {_pname} · {footer_text}"

    member_color = target_user.color if target_user.color.value != 0 else EMBED_COLORS["general"]

    return obsidian_embed(
        f"👤 {target_user.display_name}",
        desc,
        color=member_color,
        template="profile",
        category="general",
        author=target_user,
        thumbnail=target_user.display_avatar.url,
        fields=fields,
        footer=footer_text,
        client=client,
    )


def setup(bot, group=None):
    """Register the profile command under general and as top-level /profile shortcut."""
    @app_commands.describe(
        user="The user to view the profile of (defaults to yourself)",
        share="Post your profile publicly in the channel for others to see (default: False)",
    )
    async def profile_callback(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        share: bool = False,
    ):
        """Display a comprehensive user profile."""
        # When sharing own profile: public. Viewing someone else: always public.
        # Viewing own profile without share: ephemeral.
        is_self = user is None or (isinstance(interaction.user, discord.Member) and user.id == interaction.user.id)
        defer_ephemeral = is_self and not share
        if not share and not defer_ephemeral and interaction.guild:
            # Respect the user's "private results" preference even when viewing others.
            from core.user_prefs import results_ephemeral
            if await results_ephemeral(interaction.guild.id, interaction.user.id):
                defer_ephemeral = True
        await interaction.response.defer(ephemeral=defer_ephemeral)

        if not interaction.guild:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Profiles with server stats can only be viewed in a server.",
                    template="error",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        target_user = user or interaction.user
        if not isinstance(target_user, discord.Member):
            return await interaction.followup.send("User not found in this server.", ephemeral=True)
        
        profile_data = await get_user_profile_data(interaction.guild.id, target_user.id)
        if is_self:
            try:
                from commands.general.onboarding import record_onboarding_step

                await record_onboarding_step(interaction.guild.id, interaction.user.id, "view_profile")
            except Exception:
                pass
        current_level = profile_data["level"]
        voice_hours = profile_data["voice_minutes"] // 60
        voice_mins = profile_data["voice_minutes"] % 60
        voice_time = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"

        embed = await build_profile_embed(
            interaction.guild,
            target_user,
            profile_data,
            viewer=interaction.user,
            client=interaction.client,
        )

        from core.profile_layout import ProfileFullLayout, profile_layout_v2_enabled

        if profile_layout_v2_enabled() and is_self and defer_ephemeral:
            try:
                fields = [(f.name, f.value, f.inline) for f in embed.fields]
                layout = ProfileFullLayout(
                    title=f"👤 {target_user.display_name}",
                    description=embed.description or "",
                    fields=fields,
                )
                await interaction.followup.send(view=layout, ephemeral=True)
                return
            except Exception:
                pass
        await interaction.followup.send(embed=embed, ephemeral=defer_ephemeral)

    group.command(name="profile", description="View your or another user's profile and statistics.")(profile_callback)
    shortcut = app_commands.Command(name="profile", description="View profile (shortcut for /general profile)", callback=profile_callback)
    bot.tree.add_command(shortcut)

    bio_decorator = group.command(name="set_bio", description="Set a short bio that appears on your profile card.") if group else bot.tree.command(name="set_bio", description="Set a short bio for your profile.")

    @bio_decorator
    async def set_bio(interaction: discord.Interaction):
        """Open a modal to set your profile bio."""
        await interaction.response.send_modal(BioModal())
