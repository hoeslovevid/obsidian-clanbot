"""Transaction history command - view recent coin transactions."""
import discord
from discord import app_commands
from datetime import datetime

from utils import obsidian_embed, error_embed, ECONOMY_ENABLED
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the transactions command."""
    command_decorator = (
        group.command(name="transactions", description="View your recent coin transaction history.")
        if group
        else bot.tree.command(name="transactions", description="View your recent coin transaction history.")
    )

    @command_decorator
    @app_commands.describe(
        limit="Number of transactions to show (default: 15, max: 25)",
        user="View another user's transactions (moderators only)"
    )
    async def transactions(interaction: discord.Interaction, limit: int = 15, user: discord.Member = None):
        """Display recent coin transactions."""
        await interaction.response.defer(ephemeral=True)

        if not ECONOMY_ENABLED:
            return await interaction.followup.send(
                embed=error_embed("Economy Disabled", "The economy system is currently disabled.", client=interaction.client),
                ephemeral=True
            )

        if not interaction.guild:
            return await interaction.followup.send(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True
            )

        target = user or interaction.user
        is_mod = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if user and target.id != interaction.user.id and not is_mod:
            return await interaction.followup.send(
                embed=error_embed("Permission Denied", "You can only view your own transaction history.", client=interaction.client),
                ephemeral=True
            )

        limit = max(1, min(25, limit))

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, target.id),
            )
            bal_row = await cur.fetchone()
            current_balance = bal_row[0] or 0 if bal_row else 0
            cur = await db.execute("""
                SELECT amount, transaction_type, description, created_at
                FROM economy_transactions
                WHERE guild_id=? AND user_id=?
                ORDER BY created_at DESC
                LIMIT ?
            """, (interaction.guild.id, target.id, limit))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📜 Transaction History",
                    f"No transactions yet for {target.mention}.\n\nUse `/daily`, send messages, or join voice to earn coins!",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        lines = []
        running_balance = current_balance
        for amount, txn_type, desc, created_at in rows:
            sign = "+" if amount >= 0 else ""
            type_label = txn_type.replace("_", " ").title() if txn_type else "?"
            desc_short = (desc[:35] + "…") if desc and len(desc) > 35 else (desc or "")
            try:
                ts = int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()) if created_at else 0
                time_str = f"<t:{ts}:R>" if ts else "?"
            except Exception:
                time_str = created_at[:19].replace("T", " ") if created_at else "?"
            emoji = "💰" if amount >= 0 else "📤"
            lines.append(f"{emoji} **{sign}{amount:,}** {type_label} — {desc_short}\n   {time_str} → **{running_balance:,}**")
            running_balance -= amount

        desc_text = "\n\n".join(lines)
        title = f"📜 Transactions for {target.display_name}"
        embed = obsidian_embed(
            title,
            desc_text,
            color=discord.Color.gold(),
            author=target,
            thumbnail=target.display_avatar.url if target.display_avatar else None,
            footer=f"Balance: {current_balance:,} coins • Showing last {len(rows)} • Use limit:N for more",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
