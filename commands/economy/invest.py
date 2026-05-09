"""Investment system command."""
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED
from database import DB_PATH, remove_coins, add_coins
import aiosqlite  # type: ignore


EARLY_WITHDRAWAL_PENALTY = 0.15  # 15% penalty on principal


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class EarlyWithdrawConfirmView(discord.ui.View):
    """Confirmation flow for early investment withdrawal."""

    def __init__(self, investment_id: int, amount: int, payout: int, penalty: int):
        super().__init__(timeout=60)
        self.investment_id = investment_id
        self.amount = amount
        self.payout = payout
        self.penalty = penalty

    @discord.ui.button(label="✅ Confirm Withdrawal", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        # Mark as collected
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id FROM investments WHERE id=? AND collected=0",
                (self.investment_id,),
            )
            if not await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Already Collected",
                        "This investment has already been collected or withdrawn.",
                        category="error",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            await db.execute("UPDATE investments SET collected=1 WHERE id=?", (self.investment_id,))
            await db.commit()

        if not interaction.guild:
            return
        await add_coins(
            interaction.guild.id,
            interaction.user.id,
            self.payout,
            "INVESTMENT_WITHDRAW",
            f"Early withdrawal: {self.amount:,} principal − {self.penalty:,} penalty",
        )
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        embed = obsidian_embed(
            "💸 Investment Withdrawn Early",
            f"> You received **{self.payout:,}** coins back.\n"
            f"-# {self.penalty:,} coins lost to the early withdrawal penalty.",
            category="economy",
            fields=[
                ("💰 Principal", f"{self.amount:,} coins", True),
                ("🔻 Penalty (15%)", f"−{self.penalty:,} coins", True),
                ("✅ Returned", f"{self.payout:,} coins", True),
            ],
            client=interaction.client,
        )
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="✖ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            embed=obsidian_embed(
                "↩️ Withdrawal Cancelled",
                "Your investment remains active.",
                category="economy",
                client=interaction.client,
            ),
            view=self,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


def setup(bot, group=None):
    """Register the invest command."""
    
    command_decorator = group.command(name="invest", description="Invest coins to earn interest over time.") if group else bot.tree.command(name="invest", description="Invest coins to earn interest over time.")
    
    @command_decorator
    @app_commands.describe(
        amount="Amount of coins to invest",
        duration="Investment duration in days (7, 14, 30, or 90)"
    )
    @app_commands.choices(duration=[
        app_commands.Choice(name="7 days (5%)", value=7),
        app_commands.Choice(name="14 days (10%)", value=14),
        app_commands.Choice(name="30 days (25%)", value=30),
        app_commands.Choice(name="90 days (100%)", value=90),
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            balance = row[0] or 0 if row else 0
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
        
        fields = [
            ("💰 Invested", f"{amount:,} coins", True),
            ("📈 Interest", f"{interest_rate * 100:.0f}%", True),
            ("💎 Total Return", f"{total_return:,} coins (+{profit:,})", True),
            ("⏰ Matures", f"<t:{int(maturity_date.timestamp())}:F>", False),
        ]
        embed = obsidian_embed(
            "✅ Investment Created",
            f"Your investment is locked for **{duration.value} days**. Use `/invest_status` to check progress.",
            color=discord.Color.green(),
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            fields=fields,
            footer=f"Matures <t:{int(maturity_date.timestamp())}:R>",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="invest_status", description="Check your investment status.") if group else bot.tree.command(name="invest_status", description="Check your investment status.")
    
    @command_decorator
    async def invest_status(interaction: discord.Interaction):
        """Check investment status."""
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
        
        embed = obsidian_embed(
            "💼 Investment Status",
            desc,
            color=discord.Color.blue(),
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=f"Use /invest_collect when ready",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="invest_collect", description="Collect your matured investment returns.") if group else bot.tree.command(name="invest_collect", description="Collect your matured investment returns.")
    
    @command_decorator
    async def invest_collect(interaction: discord.Interaction):
        """Collect investment returns."""
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
        
        embed = obsidian_embed(
            "✅ Investment Collected",
            f"You collected **{total_return:,}** coins from your investment!\n\n"
            f"**Original:** {amount:,} coins\n"
            f"**Profit:** {profit:,} coins\n"
            f"**Total:** {total_return:,} coins",
            color=discord.Color.green(),
            thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            footer=f"+{profit:,} profit",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    withdraw_decorator = (
        group.command(name="invest_withdraw", description="Withdraw your investment early (15% penalty on principal).")
        if group
        else bot.tree.command(name="invest_withdraw", description="Withdraw your investment early (15% penalty on principal).")
    )

    @withdraw_decorator
    async def invest_withdraw(interaction: discord.Interaction):
        """Withdraw an active investment early with a 15% penalty."""
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    category="error",
                    client=interaction.client,
                ),
                ephemeral=True,
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
                    "❌ No Active Investment",
                    "You don't have an active investment to withdraw.",
                    category="error",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        investment_id, amount, interest_rate, maturity_date_str = row
        maturity_date = datetime.fromisoformat(maturity_date_str.replace("Z", "+00:00"))

        if now_utc() >= maturity_date:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Investment Already Matured",
                    f"Your investment has matured — use `/invest_collect` to collect **{int(amount * (1 + interest_rate)):,}** coins (no penalty).",
                    category="economy",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        penalty = int(amount * EARLY_WITHDRAWAL_PENALTY)
        payout  = amount - penalty

        embed = obsidian_embed(
            "⚠️ Early Withdrawal — Confirm",
            f"> Withdrawing now forfeits **{penalty:,} coins** (15% of your {amount:,} principal).\n"
            f"> You will receive **{payout:,} coins** back.\n\n"
            f"The investment matures <t:{int(maturity_date.timestamp())}:R> — waiting means no penalty.\n"
            f"-# This action cannot be undone.",
            category="warning",
            fields=[
                ("💰 Principal", f"{amount:,} coins", True),
                ("🔻 Penalty (15%)", f"−{penalty:,} coins", True),
                ("✅ You'd Receive", f"{payout:,} coins", True),
            ],
            client=interaction.client,
        )
        view = EarlyWithdrawConfirmView(investment_id, amount, payout, penalty)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
