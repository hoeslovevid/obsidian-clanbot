"""Voice activity leaderboards."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite


async def get_voice_leaderboard(guild_id: int, period: str = "all_time", limit: int = 10) -> list:
    """Get voice activity leaderboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        if period == "all_time":
            cur = await db.execute("""
                SELECT user_id, voice_minutes
                FROM activity_stats
                WHERE guild_id=?
                ORDER BY voice_minutes DESC
                LIMIT ?
            """, (guild_id, limit))
        elif period == "weekly":
            cur = await db.execute("""
                SELECT user_id, weekly_score
                FROM activity_stats
                WHERE guild_id=?
                ORDER BY weekly_score DESC
                LIMIT ?
            """, (guild_id, limit))
        elif period == "monthly":
            cur = await db.execute("""
                SELECT user_id, monthly_score
                FROM activity_stats
                WHERE guild_id=?
                ORDER BY monthly_score DESC
                LIMIT ?
            """, (guild_id, limit))
        else:
            cur = await db.execute("""
                SELECT user_id, voice_minutes
                FROM activity_stats
                WHERE guild_id=?
                ORDER BY voice_minutes DESC
                LIMIT ?
            """, (guild_id, limit))
        
        return await cur.fetchall()


def setup(bot, group=None):
    """Register voice leaderboard commands."""
    # Voice leaderboard command
    leaderboard_decorator = group.command(name="voice_leaderboard", description="View voice activity leaderboard.") if group else bot.tree.command(name="voice_leaderboard", description="View voice activity leaderboard.")
    
    @leaderboard_decorator
    @app_commands.describe(
        period="Time period for the leaderboard",
        limit="Number of users to show (max 20)"
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="All Time", value="all_time"),
        app_commands.Choice(name="Weekly", value="weekly"),
        app_commands.Choice(name="Monthly", value="monthly"),
    ])
    async def voice_leaderboard(interaction: discord.Interaction, period: str = "all_time", limit: int = 10):
        """View voice activity leaderboard."""
        await interaction.response.defer(ephemeral=False)
        
        if limit > 20:
            limit = 20
        if limit < 1:
            limit = 10
        
        leaderboard = await get_voice_leaderboard(interaction.guild.id, period, limit)
        
        if not leaderboard:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🎤 Voice Activity Leaderboard",
                    "No voice activity data available yet.",
                    color=discord.Color.blurple(),
                    client=interaction.client,
                )
            )
        
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, score) in enumerate(leaderboard):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            if period == "all_time":
                hours = score // 60
                minutes = score % 60
                score_text = f"{hours}h {minutes}m"
            elif period in ("weekly", "monthly"):
                score_text = f"{score:,} pts"
            else:
                score_text = str(score)
            leaderboard_text += f"{medal} **{username}** — {score_text}\n"
        
        period_name = period.replace("_", " ").title()
        thumb_url = None
        if leaderboard:
            top_user = interaction.guild.get_member(leaderboard[0][0])
            if top_user and top_user.display_avatar:
                thumb_url = top_user.display_avatar.url
        
        embed = obsidian_embed(
            f"🎤 Voice Leaderboard - {period_name}",
            leaderboard_text.strip(),
            color=discord.Color.blue(),
            thumbnail=thumb_url,
            footer=f"{interaction.guild.name} • Top {len(leaderboard)} voice users",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
