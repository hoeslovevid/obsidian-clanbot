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
        
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Check last claim
            cur = await db.execute(
                "SELECT last_claim_date, streak_days, freeze_used_month FROM daily_claims WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            
            if row:
                last_claim_date, streak_days = row[0], int(row[1])
                freeze_used_month = row[2] if len(row) > 2 else None
                
                # Check if already claimed today
                if last_claim_date == today:
                    from datetime import timedelta as _td
                    tomorrow_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + _td(days=1)
                    next_ts = int(tomorrow_dt.timestamp())
                    streak_fire = "🔥" * min(streak_days, 10) + (f" +{streak_days - 10}" if streak_days > 10 else "")
                    fields = [
                        ("🔥 Current Streak", f"{streak_fire}\n{streak_days} day(s)", True),
                        ("⏰ Next Claim", f"<t:{next_ts}:R>", True),
                    ]
                    
                    embed = obsidian_embed(
                        "⏰ Already Claimed",
                        "You've already claimed your daily reward today!",
                        color=discord.Color.orange(),
                        fields=fields,
                        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                        footer="Come back tomorrow for your next reward",
                        client=interaction.client,
                    )
                    return await interaction.response.send_message(embed=embed, ephemeral=True)
                
                # Check if streak continues (claimed yesterday) or use streak freeze
                yesterday = datetime.now(timezone.utc).date()
                from datetime import timedelta
                yesterday_str = (yesterday - timedelta(days=1)).isoformat()
                
                if last_claim_date == yesterday_str:
                    # Streak continues
                    new_streak = streak_days + 1
                    used_freeze = False
                elif freeze_used_month != current_month:
                    # Streak freeze: one per month - keep streak, use freeze
                    new_streak = streak_days
                    used_freeze = True
                else:
                    # Streak broken, reset to 1
                    new_streak = 1
                    used_freeze = False
            else:
                # First time claiming
                new_streak = 1
                used_freeze = False
            
            # Award coins
            await add_coins(
                interaction.guild.id,
                interaction.user.id,
                COINS_DAILY_REWARD,
                "DAILY",
                f"Daily reward (streak: {new_streak})",
            )
            
            # Update or insert claim record (set freeze_used_month when freeze is used)
            freeze_val = current_month if used_freeze else None
            await db.execute("""
                INSERT INTO daily_claims (guild_id, user_id, last_claim_date, streak_days, freeze_used_month)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_claim_date = excluded.last_claim_date,
                    streak_days = excluded.streak_days,
                    freeze_used_month = COALESCE(excluded.freeze_used_month, freeze_used_month)
            """, (
                interaction.guild.id,
                interaction.user.id,
                today,
                new_streak,
                freeze_val,
            ))
            await db.commit()
            if new_streak >= 10:
                try:
                    from database import check_and_unlock_achievement
                    await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "daily_streak_10", None)
                except Exception:
                    pass

        # Success message with streak visualization and next claim time
        streak_fire = "🔥" * min(new_streak, 10) + (f" +{new_streak - 10}" if new_streak > 10 else "")
        tomorrow = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        tomorrow = tomorrow + timedelta(days=1)
        next_ts = int(tomorrow.timestamp())
        next_line = f"Next daily: <t:{next_ts}:R>"

        fields = [
            ("💰 Reward", f"**{COINS_DAILY_REWARD:,}** coins", True),
            ("🔥 Streak", f"{streak_fire}\n{new_streak} day(s)", True),
            ("⏰ Next Claim", next_line, True),
        ]
        if used_freeze:
            fields.append(("🛡️ Streak Freeze", "Used 1 monthly freeze to preserve streak", True))

        # Celebratory style for milestones
        if new_streak >= 100:
            title, color = "💯 Century Streak!", discord.Color.purple()
        elif new_streak >= 30:
            title, color = "🌟 30-Day Streak!", discord.Color.gold()
        elif new_streak >= 10:
            title, color = "🔥 10-Day Streak!", discord.Color.orange()
        else:
            title, color = "🎁 Daily Reward Claimed!", discord.Color.green()

        embed = obsidian_embed(
            title,
            "Come back tomorrow for another reward!" + ("\n\n_Used streak freeze (1 per month)._" if used_freeze else ""),
            color=color,
            fields=fields,
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer="Use /daily tomorrow • Streak resets if you miss a day",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
