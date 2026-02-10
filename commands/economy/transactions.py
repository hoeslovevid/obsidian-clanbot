"""Transaction history command - view recent coin transactions."""
import discord
from discord import app_commands

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

        from database import get_user_balance
        current_balance = await get_user_balance(interaction.guild.id, target.id)

        async with aiosqlite.connect(DB_PATH) as db:
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
            # Shorten type for display (e.g. TRANSFER_IN -> Transfer In)
            type_label = txn_type.replace("_", " ").title() if txn_type else "?"
            desc_short = (desc[:40] + "…") if desc and len(desc) > 40 else (desc or "")
            time_str = created_at[:19].replace("T", " ") if created_at else "?"
            lines.append(f"**{sign}{amount:,}** {type_label} — {desc_short} — {time_str} → **{running_balance:,}**")
            running_balance -= amount

        desc_text = "\n".join(lines)
        title = f"📜 Transactions for {target.display_name}"
        embed = obsidian_embed(
            title,
            desc_text,
            color=discord.Color.gold(),
            author=target,
            footer=f"Last {len(rows)} transaction(s)",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
