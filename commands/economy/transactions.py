"""Transaction history command - view recent coin transactions."""
import discord
from discord import app_commands
from datetime import datetime
import io
import csv

from core.utils import obsidian_embed, error_embed, feature_off_embed, ECONOMY_ENABLED
from database import DB_PATH
import aiosqlite

MAX_EXPORT_ROWS = 500


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
        user="View another user's transactions (moderators only)",
        type="Filter by transaction type"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Daily", value="DAILY"),
        app_commands.Choice(name="Transfer", value="TRANSFER"),
        app_commands.Choice(name="Gambling", value="GAMBLING"),
        app_commands.Choice(name="Investment", value="INVESTMENT"),
        app_commands.Choice(name="Investment Return", value="INVESTMENT_RETURN"),
        app_commands.Choice(name="Shop Purchase", value="SHOP_PURCHASE"),
        app_commands.Choice(name="Mod Add/Remove", value="mod"),
    ])
    async def transactions(interaction: discord.Interaction, limit: int = 15, user: discord.Member = None, type: app_commands.Choice[str] = None):
        """Display recent coin transactions."""
        await interaction.response.defer(ephemeral=True)

        if not ECONOMY_ENABLED:
            return await interaction.followup.send(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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
        txn_filter = type.value if type and type.value != "all" else None

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, target.id),
            )
            bal_row = await cur.fetchone()
            current_balance = bal_row[0] or 0 if bal_row else 0
            if txn_filter:
                if txn_filter == "mod":
                    cur = await db.execute("""
                        SELECT amount, transaction_type, description, created_at
                        FROM economy_transactions
                        WHERE guild_id=? AND user_id=? AND transaction_type IN ('MOD_ADD','MOD_REMOVE')
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (interaction.guild.id, target.id, limit))
                else:
                    cur = await db.execute("""
                        SELECT amount, transaction_type, description, created_at
                        FROM economy_transactions
                        WHERE guild_id=? AND user_id=? AND transaction_type=?
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (interaction.guild.id, target.id, txn_filter, limit))
            else:
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
            footer=f"Balance: {current_balance:,} coins • Showing last {len(rows)}{f' ({txn_filter})' if txn_filter else ''} • Use type: to filter",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Export transactions as CSV
    export_decorator = (
        group.command(name="export_transactions", description="Export your transaction history as CSV (DMed to you).")
        if group
        else bot.tree.command(name="export_transactions", description="Export your transaction history as CSV.")
    )

    @export_decorator
    @app_commands.describe(limit="Max transactions to export (default: 100, max: 500)")
    async def export_transactions(interaction: discord.Interaction, limit: int = 100):
        """Export transaction history as CSV file."""
        await interaction.response.defer(ephemeral=True)

        if not ECONOMY_ENABLED:
            return await interaction.followup.send(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
                ephemeral=True
            )

        if not interaction.guild:
            return await interaction.followup.send(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True
            )

        limit = max(1, min(MAX_EXPORT_ROWS, limit))
        target = interaction.user

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
                    "📜 Export Transactions",
                    "You have no transactions to export.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Date", "Amount", "Type", "Description"])
        for amount, txn_type, desc, created_at in reversed(rows):
            writer.writerow([
                created_at[:19].replace("T", " ") if created_at else "",
                amount,
                txn_type or "",
                (desc or "").replace("\n", " "),
            ])

        buffer.seek(0)
        file = discord.File(io.BytesIO(buffer.getvalue().encode("utf-8-sig")), filename=f"transactions_{target.id}.csv")

        try:
            await target.send(
                embed=obsidian_embed(
                    "📜 Transaction Export",
                    f"Exported {len(rows)} transaction(s) from {interaction.guild.name}.",
                    color=discord.Color.gold(),
                    client=interaction.client,
                ),
                file=file,
            )
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Export Sent",
                    f"CSV with {len(rows)} transaction(s) has been DMed to you.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(
                    "Cannot DM",
                    "Enable DMs from server members to receive the export, or use `/economy transactions` to view in-channel.",
                    client=interaction.client,
                ),
                ephemeral=True
            )
