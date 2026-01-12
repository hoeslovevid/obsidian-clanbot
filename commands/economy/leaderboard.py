"""Leaderboard command."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED


def setup(bot):
    """Register the leaderboard command."""
    @bot.tree.command(name="leaderboard", description="View the top coin earners.")
    @app_commands.describe(limit="Number of users to show (default: 10, max: 25)")
    async def leaderboard(interaction: discord.Interaction, limit: int = 10):
        """Display the top coin earners."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import DB_PATH
        import aiosqlite
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message("Economy system is disabled.", ephemeral=True)
        
        if limit < 1 or limit > 25:
            limit = 10
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, balance, total_earned
                FROM user_balances
                WHERE guild_id=?
                ORDER BY balance DESC
                LIMIT ?
            """, (interaction.guild.id, limit))
            rows = await cur.fetchall()
        
        if not rows:
            return await interaction.response.send_message("No users have earned coins yet!", ephemeral=True)
        
        desc = ""
        for i, (user_id, balance, total_earned) in enumerate(rows, 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            desc += f"{medal} **{username}** - {balance:,} coins (Total earned: {total_earned:,})\n"
        
        embed = obsidian_embed(
            "🏆 Coin Leaderboard",
            desc,
            color=discord.Color.gold(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
