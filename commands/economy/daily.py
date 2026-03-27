"""Daily reward command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, COINS_DAILY_REWARD, format_number, pluralize, EMBED_COLORS


def setup(bot, group=None):
    """Register the daily command under /economy and as top-level /daily shortcut."""
    async def daily_callback(interaction: discord.Interaction):
        await _run_daily(interaction)

    group.command(name="daily", description="Claim your daily coin reward!")(daily_callback)
    # Top-level /daily shortcut
    shortcut = app_commands.Command(name="daily", description="Claim your daily coin reward! (shortcut for /economy daily)", callback=daily_callback)
    bot.tree.add_command(shortcut)
    
async def _run_daily(interaction: discord.Interaction):
    """Claim daily coins (once per day)."""
    if not ECONOMY_ENABLED:
        return await interaction.response.send_message(
            embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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

    await interaction.response.defer(ephemeral=True)

    # Import bot-specific functions inside to avoid circular imports
    from bot import add_coins, DB_PATH
    import aiosqlite

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
                return await interaction.followup.send(embed=embed, ephemeral=True)

            # Check if streak continues (claimed yesterday) or use streak freeze
            yesterday = datetime.now(timezone.utc).date()
            from datetime import timedelta
            yesterday_str = (yesterday - timedelta(days=1)).isoformat()

            if last_claim_date == yesterday_str:
                new_streak = streak_days + 1
                used_freeze = False
            elif freeze_used_month != current_month:
                new_streak = streak_days
                used_freeze = True
            else:
                new_streak = 1
                used_freeze = False
        else:
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
        try:
            from database import check_and_unlock_achievement, get_user_balance
            bal = await get_user_balance(interaction.guild.id, interaction.user.id)
            if bal >= 1_000_000:
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "first_million", None)
        except Exception:
            pass
        try:
            from database import check_and_unlock_achievement
            if isinstance(interaction.user, discord.Member) and interaction.user.joined_at:
                days_in = (datetime.now(timezone.utc) - interaction.user.joined_at.replace(tzinfo=timezone.utc)).days
                for months, ach_id in [(3, "months_3"), (6, "months_6")]:
                    if days_in >= months * 30:
                        await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, ach_id, None)
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
        ("💰 Reward", f"**{format_number(COINS_DAILY_REWARD)}** {pluralize(COINS_DAILY_REWARD, 'coin')}", True),
        ("🔥 Streak", f"{streak_fire}\n{new_streak} {pluralize(new_streak, 'day')}", True),
        ("⏰ Next Claim", next_line, True),
    ]
    if used_freeze:
        fields.append(("🛡️ Streak Freeze", "Used 1 monthly freeze to preserve streak", True))

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
        f"**You received {format_number(COINS_DAILY_REWARD)} {pluralize(COINS_DAILY_REWARD, 'coin')}.** "
        "Come back after reset for the next one!"
        + ("\n\n_Used your monthly streak freeze._" if used_freeze else ""),
        color=color,
        fields=fields,
        thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        footer="What's next? /economy shop or /economy gamble • Streak resets if you miss a day",
        client=interaction.client,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
