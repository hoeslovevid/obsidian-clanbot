"""Daily reward command."""
import discord
from datetime import datetime, timezone

from utils import obsidian_embed, ECONOMY_ENABLED, COINS_DAILY_REWARD


def setup(bot, group=None):
    """Register the daily command."""
    command_decorator = group.command(name="daily", description="Claim your daily coin reward!") if group else bot.tree.command(name="daily", description="Claim your daily coin reward!")
    
    @command_decorator
    async def daily(interaction: discord.Interaction):
        """Claim daily coins (once per day)."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import add_coins, DB_PATH
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
        
        # Get current date in UTC
        today = datetime.now(timezone.utc).date().isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Check last claim
            cur = await db.execute(
                "SELECT last_claim_date, streak_days FROM daily_claims WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            
            if row:
                last_claim_date, streak_days = row[0], int(row[1])
                
                # Check if already claimed today
                if last_claim_date == today:
                    # Calculate time until next claim (next day in UTC)
                    tomorrow = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    tomorrow = tomorrow.replace(day=tomorrow.day + 1)
                    time_until = tomorrow - datetime.now(timezone.utc)
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    
                    fields = [
                        ("🔥 Current Streak", f"{streak_days} day(s)", True),
                        ("⏰ Next Claim", f"{hours}h {minutes}m", True),
                    ]
                    
                    return await interaction.response.send_message(
                        embed=obsidian_embed(
                            "⏰ Already Claimed",
                            "You've already claimed your daily reward today!",
                            color=discord.Color.orange(),
                            fields=fields,
                            client=interaction.client,
                        ),
                        ephemeral=True,
                    )
                
                # Check if streak continues (claimed yesterday)
                yesterday = datetime.now(timezone.utc).date()
                from datetime import timedelta
                yesterday = (yesterday - timedelta(days=1)).isoformat()
                
                if last_claim_date == yesterday:
                    # Streak continues
                    new_streak = streak_days + 1
                else:
                    # Streak broken, reset to 1
                    new_streak = 1
            else:
                # First time claiming
                new_streak = 1
            
            # Award coins
            await add_coins(
                interaction.guild.id,
                interaction.user.id,
                COINS_DAILY_REWARD,
                "DAILY",
                f"Daily reward (streak: {new_streak})",
            )
            
            # Update or insert claim record
            await db.execute("""
                INSERT INTO daily_claims (guild_id, user_id, last_claim_date, streak_days)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_claim_date = ?,
                    streak_days = ?
            """, (
                interaction.guild.id,
                interaction.user.id,
                today,
                new_streak,
                today,
                new_streak,
            ))
            await db.commit()
        
        # Success message
        fields = [
            ("💰 Reward", f"**{COINS_DAILY_REWARD:,}** coins", True),
            ("🔥 Streak", f"{new_streak} day(s)", True),
        ]
        
        embed = obsidian_embed(
            "🎁 Daily Reward Claimed!",
            "Come back tomorrow for another reward!",
            color=discord.Color.green(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
