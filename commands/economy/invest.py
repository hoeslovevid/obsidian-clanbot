"""Investment system command."""
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils import obsidian_embed, ECONOMY_ENABLED
from database import DB_PATH, get_user_balance, remove_coins, add_coins
import aiosqlite  # type: ignore


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def setup(bot, group=None):
    """Register the invest command."""
    
    command_decorator = group.command(name="invest", description="Invest coins to earn interest over time.") if group else bot.tree.command(name="invest", description="Invest coins to earn interest over time.")
    
    @command_decorator
    @app_commands.describe(
        amount="Amount of coins to invest",
        duration="Investment duration in days (7, 14, 30, or 90)"
    )
    @app_commands.choices(duration=[
        app_commands.Choice(name="7 days (5% interest)", value=7),
        app_commands.Choice(name="14 days (10% interest)", value=14),
        app_commands.Choice(name="30 days (25% interest)", value=30),
        app_commands.Choice(name="90 days (100% interest)", value=90),
    ])
    async def invest(interaction: discord.Interaction, amount: int, duration: app_commands.Choice[int]):
        """Invest coins for returns."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        if amount < 100:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Minimum Investment",
                    "Minimum investment is 100 coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check balance
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        if balance < amount:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Insufficient Balance",
                    f"You have insufficient balance. You currently have **{balance:,}** coins.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Calculate interest rates
        interest_rates = {7: 0.05, 14: 0.10, 30: 0.25, 90: 1.00}
        interest_rate = interest_rates.get(duration.value, 0.05)
        total_return = int(amount * (1 + interest_rate))
        profit = total_return - amount
        
        # Check for existing investment
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT COUNT(*) FROM investments 
                WHERE guild_id=? AND user_id=? AND collected=0
            """, (interaction.guild.id, interaction.user.id))
            existing_count = (await cur.fetchone())[0]
            
            if existing_count > 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Active Investment Exists",
                        "You already have an active investment. Wait for it to mature before investing again.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Remove coins
        success = await remove_coins(
            interaction.guild.id,
            interaction.user.id,
            amount,
            "INVESTMENT",
            f"Investment for {duration.value} days"
        )
        
        if not success:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Transaction Failed",
                    "Failed to process investment. Please try again.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Create investment
        now = now_utc()
        maturity_date = now + timedelta(days=duration.value)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO investments (guild_id, user_id, amount, interest_rate, invested_at, maturity_date, collected)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                interaction.guild.id,
                interaction.user.id,
                amount,
                interest_rate,
                now.isoformat(),
                maturity_date.isoformat()
            ))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Investment Created",
                f"You invested **{amount:,}** coins for **{duration.value} days**.\n\n"
                f"**Interest Rate:** {interest_rate * 100:.0f}%\n"
                f"**Total Return:** {total_return:,} coins\n"
                f"**Profit:** {profit:,} coins\n"
                f"**Matures:** <t:{int(maturity_date.timestamp())}:F>\n\n"
                f"Use `/invest_status` to check your investment.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="invest_status", description="Check your investment status.") if group else bot.tree.command(name="invest_status", description="Check your investment status.")
    
    @command_decorator
    async def invest_status(interaction: discord.Interaction):
        """Check investment status."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT amount, interest_rate, invested_at, maturity_date, collected
                FROM investments
                WHERE guild_id=? AND user_id=? AND collected=0
                ORDER BY invested_at DESC
                LIMIT 1
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "💼 No Active Investment",
                    "You don't have an active investment. Use `/invest` to start investing!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        amount, interest_rate, invested_at, maturity_date_str, collected = row
        maturity_date = datetime.fromisoformat(maturity_date_str.replace('Z', '+00:00'))
        now = now_utc()
        
        total_return = int(amount * (1 + interest_rate))
        profit = total_return - amount
        
        if now >= maturity_date:
            # Investment matured - allow collection
            desc = f"**Investment Amount:** {amount:,} coins\n"
            desc += f"**Interest Rate:** {interest_rate * 100:.0f}%\n"
            desc += f"**Total Return:** {total_return:,} coins\n"
            desc += f"**Profit:** {profit:,} coins\n"
            desc += f"**Status:** ✅ Ready to collect!\n\n"
            desc += f"Use `/invest_collect` to collect your returns."
        else:
            time_remaining = maturity_date - now
            days = time_remaining.days
            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            desc = f"**Investment Amount:** {amount:,} coins\n"
            desc += f"**Interest Rate:** {interest_rate * 100:.0f}%\n"
            desc += f"**Total Return:** {total_return:,} coins\n"
            desc += f"**Profit:** {profit:,} coins\n"
            desc += f"**Time Remaining:** {days}d {hours}h {minutes}m\n"
            desc += f"**Matures:** <t:{int(maturity_date.timestamp())}:F>"
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "💼 Investment Status",
                desc,
                color=discord.Color.blue(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    command_decorator = group.command(name="invest_collect", description="Collect your matured investment returns.") if group else bot.tree.command(name="invest_collect", description="Collect your matured investment returns.")
    
    @command_decorator
    async def invest_collect(interaction: discord.Interaction):
        """Collect investment returns."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, amount, interest_rate, maturity_date
                FROM investments
                WHERE guild_id=? AND user_id=? AND collected=0
                ORDER BY invested_at DESC
                LIMIT 1
            """, (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ No Investment Found",
                    "You don't have an active investment to collect.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        investment_id, amount, interest_rate, maturity_date_str = row
        maturity_date = datetime.fromisoformat(maturity_date_str.replace('Z', '+00:00'))
        now = now_utc()
        
        if now < maturity_date:
            time_remaining = maturity_date - now
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⏳ Investment Not Matured",
                    f"Your investment hasn't matured yet. It will be ready <t:{int(maturity_date.timestamp())}:R>.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Calculate returns
        total_return = int(amount * (1 + interest_rate))
        profit = total_return - amount
        
        # Mark as collected and add coins
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE investments SET collected=1 WHERE id=?
            """, (investment_id,))
            await db.commit()
        
        await add_coins(
            interaction.guild.id,
            interaction.user.id,
            total_return,
            "INVESTMENT_RETURN",
            f"Investment return: {amount:,} + {profit:,} profit"
        )
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Investment Collected",
                f"You collected **{total_return:,}** coins from your investment!\n\n"
                f"**Original:** {amount:,} coins\n"
                f"**Profit:** {profit:,} coins\n"
                f"**Total:** {total_return:,} coins",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
