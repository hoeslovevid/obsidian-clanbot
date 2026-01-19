"""Activity leaderboard command."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register the activity_leaderboard command."""
    command_decorator = group.command(name="activity_leaderboard", description="View the most active members in the server.") if group else bot.tree.command(name="activity_leaderboard", description="View the most active members in the server.")
    
    @command_decorator
    @app_commands.describe(period="Time period for leaderboard (weekly, monthly, or all-time)")
    async def activity_leaderboard(interaction: discord.Interaction, period: str = "weekly"):
        """Show activity leaderboard."""
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        period = period.lower()
        if period not in ["weekly", "monthly", "all-time"]:
            period = "weekly"
        
        async with aiosqlite.connect(DB_PATH) as db:
            if period == "weekly":
                # Get weekly scores
                cur = await db.execute("""
                    SELECT user_id, weekly_score, commands_used, events_attended, voice_minutes
                    FROM activity_stats
                    WHERE guild_id = ?
                    ORDER BY weekly_score DESC, commands_used DESC
                    LIMIT 10
                """, (interaction.guild.id,))
                score_col = 1
                title = "📊 Weekly Activity Leaderboard"
            elif period == "monthly":
                # Get monthly scores
                cur = await db.execute("""
                    SELECT user_id, monthly_score, commands_used, events_attended, voice_minutes
                    FROM activity_stats
                    WHERE guild_id = ?
                    ORDER BY monthly_score DESC, commands_used DESC
                    LIMIT 10
                """, (interaction.guild.id,))
                score_col = 1
                title = "📊 Monthly Activity Leaderboard"
            else:
                # All-time: calculate from all stats
                cur = await db.execute("""
                    SELECT user_id, commands_used, events_attended, voice_minutes, messages_sent
                    FROM activity_stats
                    WHERE guild_id = ?
                    ORDER BY (commands_used + events_attended * 10 + (voice_minutes / 10) + (messages_sent / 50)) DESC
                    LIMIT 10
                """, (interaction.guild.id,))
                score_col = None
                title = "📊 All-Time Activity Leaderboard"
            
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📊 Activity Leaderboard",
                    "No activity data found yet. Start using commands and participating in events!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                )
            )
        
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        
        for i, row in enumerate(rows):
            user_id = row[0]
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            
            if period == "all-time":
                commands_used, events_attended, voice_minutes, messages_sent = row[1], row[2], row[3], row[4]
                score = int(commands_used + events_attended * 10 + (voice_minutes / 10) + (messages_sent / 50))
            else:
                score = row[score_col]
                commands_used = row[2]
                events_attended = row[3]
            
            medal = medals[i] if i < 3 else f"{i+1}."
            leaderboard_text += f"{medal} **{username}** - {score} pts\n"
            leaderboard_text += f"   └ Commands: {commands_used:,} | Events: {events_attended}\n"
        
        embed = obsidian_embed(
            title,
            leaderboard_text,
            color=discord.Color.gold(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
