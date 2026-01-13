"""XP Leaderboard command."""
import discord
from discord import app_commands

from utils import obsidian_embed, XP_ENABLED


def setup(bot):
    """Register the xpleaderboard command."""
    @bot.tree.command(name="xpleaderboard", description="View the top XP earners.")
    @app_commands.describe(limit="Number of users to show (default: 10, max: 25)")
    async def xpleaderboard(interaction: discord.Interaction, limit: int = 10):
        """Display the top XP earners."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import DB_PATH
        import aiosqlite
        
        if not XP_ENABLED:
            return await interaction.response.send_message("XP system is disabled.", ephemeral=True)
        
        if limit < 1 or limit > 25:
            limit = 10
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, xp, level, total_xp
                FROM user_xp
                WHERE guild_id=?
                ORDER BY xp DESC
                LIMIT ?
            """, (interaction.guild.id, limit))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.response.send_message("No users have earned XP yet!", ephemeral=True)
        
        desc = ""
        for i, (user_id, xp, level, total_xp) in enumerate(rows, 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            desc += f"{medal} **{username}** - Level {level} ({xp:,} XP)\n"
        
        embed = obsidian_embed(
            "⭐ XP Leaderboard",
            desc,
            color=discord.Color.blue(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
