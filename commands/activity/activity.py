"""Activity command to show user's activity stats."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from utils import obsidian_embed
from database import DB_PATH
import aiosqlite  # type: ignore


def setup(bot):
    """Register the activity command."""
    @bot.tree.command(name="activity", description="View your activity stats in the server.")
    async def activity(interaction: discord.Interaction):
        """Show user's activity statistics."""
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Get activity stats
            cur = await db.execute("""
                SELECT commands_used, events_attended, voice_minutes, messages_sent, weekly_score, monthly_score
                FROM activity_stats
                WHERE guild_id = ? AND user_id = ?
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
            
            if not row:
                # Initialize stats
                await db.execute("""
                    INSERT INTO activity_stats (guild_id, user_id, commands_used, events_attended, voice_minutes, messages_sent, last_activity_date, weekly_score, monthly_score)
                    VALUES (?, ?, 0, 0, 0, 0, ?, 0, 0)
                """, (interaction.guild.id, interaction.user.id, datetime.now(timezone.utc).isoformat()))
                await db.commit()
                commands_used, events_attended, voice_minutes, messages_sent, weekly_score, monthly_score = 0, 0, 0, 0, 0, 0
            else:
                commands_used, events_attended, voice_minutes, messages_sent, weekly_score, monthly_score = row
            
            # Get voice activity from voice_activity table
            cur = await db.execute("""
                SELECT SUM(total_minutes) FROM voice_activity
                WHERE guild_id = ? AND user_id = ?
            """, (interaction.guild.id, interaction.user.id))
            voice_row = await cur.fetchone()
            total_voice_minutes = voice_row[0] if voice_row and voice_row[0] else 0
            
            # Calculate activity score (weighted)
            # Commands: 1 point each, Events: 10 points each, Voice: 1 point per 10 minutes, Messages: 1 point per 50 messages
            activity_score = (
                commands_used * 1 +
                events_attended * 10 +
                (total_voice_minutes // 10) +
                (messages_sent // 50)
            )
            
            # Format voice time
            voice_hours = total_voice_minutes // 60
            voice_mins = total_voice_minutes % 60
            voice_time = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"
            
            fields = [
                ("📊 Activity Score", f"**{activity_score}** points", True),
                ("💬 Commands Used", f"{commands_used:,}", True),
                ("🎉 Events Attended", f"{events_attended}", True),
                ("🎤 Voice Time", voice_time, True),
                ("💬 Messages Sent", f"{messages_sent:,}", True),
                ("📅 Weekly Score", f"{weekly_score} points", True),
                ("📅 Monthly Score", f"{monthly_score} points", True),
            ]
            
            embed = obsidian_embed(
                f"📊 Activity Stats for {interaction.user.display_name}",
                f"Your activity in **{interaction.guild.name}**",
                color=discord.Color.blue(),
                fields=fields,
                client=interaction.client,
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
