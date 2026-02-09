"""Leaderboard command."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED


def setup(bot, group=None):
    """Register the leaderboard command."""
    command_decorator = group.command(name="leaderboard", description="View the top coin earners.") if group else bot.tree.command(name="leaderboard", description="View the top coin earners.")
    
    @command_decorator
    @app_commands.describe(limit="Number of users to show (default: 10, max: 25)")
    async def leaderboard(interaction: discord.Interaction, limit: int = 10):
        """Display the top coin earners."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import DB_PATH
        import aiosqlite
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if limit < 1 or limit > 25:
            limit = 10
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Only show users with balance > 0
            cur = await db.execute("""
                SELECT user_id, balance, total_earned
                FROM user_balances
                WHERE guild_id=? AND balance > 0
                ORDER BY balance DESC
                LIMIT ?
            """, (interaction.guild.id, limit))
            rows = await cur.fetchall()

            # "You're here": get viewer's rank if not in top N
            cur2 = await db.execute("""
                SELECT COUNT(*) + 1 FROM user_balances a
                WHERE a.guild_id=? AND a.balance > COALESCE(
                    (SELECT b.balance FROM user_balances b WHERE b.guild_id=? AND b.user_id=?), 0
                )
            """, (interaction.guild.id, interaction.guild.id, interaction.user.id))
            user_rank_row = await cur2.fetchone()
            user_rank = user_rank_row[0] if user_rank_row else None
            in_top = any(r[0] == interaction.user.id for r in rows)
        
        if not rows:
            # Check if there are any users at all in the database for debugging
            async with aiosqlite.connect(DB_PATH) as db:
                debug_cur = await db.execute("""
                    SELECT COUNT(*) FROM user_balances WHERE guild_id=?
                """, (interaction.guild.id,))
                total_count = (await debug_cur.fetchone())[0]
            
            if total_count == 0:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "📊 Leaderboard Empty",
                        "No users have earned coins yet! Start chatting or use `/daily` to earn coins.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            else:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "📊 Leaderboard Empty",
                        "No users currently have coins! Users need a balance greater than 0 to appear on the leaderboard.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Build leaderboard entries
        leaderboard_text = ""
        for i, (user_id, balance, total_earned) in enumerate(rows, 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
            leaderboard_text += f"{medal} **{username}**\n"
            leaderboard_text += f"💰 {balance:,} coins • 📊 {total_earned:,} total\n\n"

        # "You're here" when not in top N
        from database import get_user_balance
        you_line = ""
        if not in_top and user_rank is not None:
            ub = await get_user_balance(interaction.guild.id, interaction.user.id)
            if ub > 0:
                you_line = f"\n_You're here: **#{user_rank}** • {ub:,} coins_"

        embed = obsidian_embed(
            "🏆 Coin Leaderboard",
            f"Top {len(rows)} coin earners{you_line}",
            color=discord.Color.gold(),
            fields=[("Rankings", leaderboard_text.strip(), False)],
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
