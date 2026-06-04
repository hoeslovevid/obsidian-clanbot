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
TXN_PAGE_SIZE = 5


class TransactionPaginator(discord.ui.View):
    """Prev/Next pagination for transaction history (ephemeral)."""

    def __init__(
        self,
        *,
        title: str,
        pages: list[str],
        footer_base: str,
        author: discord.Member,
        client,
        txn_filter: str | None,
    ):
        super().__init__(timeout=120)
        self.title = title
        self.pages = pages
        self.footer_base = footer_base
        self.author = author
        self.client = client
        self.txn_filter = txn_filter
        self.page = 0
        self._update_buttons()

    def _update_buttons(self):
        total = max(1, len(self.pages))
        for c in self.children:
            if getattr(c, "custom_id", "") == "txn_prev":
                c.disabled = self.page <= 0
            elif getattr(c, "custom_id", "") == "txn_next":
                c.disabled = self.page >= total - 1

    def _build_embed(self) -> discord.Embed:
        total = max(1, len(self.pages))
        filter_note = f" ({self.txn_filter})" if self.txn_filter else ""
        return obsidian_embed(
            self.title,
            self.pages[self.page],
            color=discord.Color.gold(),
            author=self.author,
            thumbnail=self.author.display_avatar.url if self.author.display_avatar else None,
            footer=f"{self.footer_base} • Page {self.page + 1}/{total}{filter_note}",
            client=self.client,
        )

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="txn_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="txn_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(len(self.pages) - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


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

        title = f"📜 Transactions for {target.display_name}"
        footer_base = f"Balance: {current_balance:,} coins • Showing last {len(rows)}"
        filter_label = txn_filter if txn_filter else None

        if len(lines) <= TXN_PAGE_SIZE:
            embed = obsidian_embed(
                title,
                "\n\n".join(lines),
                color=discord.Color.gold(),
                author=target,
                thumbnail=target.display_avatar.url if target.display_avatar else None,
                footer=f"{footer_base}{f' ({txn_filter})' if txn_filter else ''} • Use type: to filter",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        page_chunks: list[str] = []
        for i in range(0, len(lines), TXN_PAGE_SIZE):
            page_chunks.append("\n\n".join(lines[i : i + TXN_PAGE_SIZE]))

        paginator = TransactionPaginator(
            title=title,
            pages=page_chunks,
            footer_base=footer_base,
            author=target,
            client=interaction.client,
            txn_filter=filter_label,
        )
        await interaction.followup.send(
            embed=paginator._build_embed(),
            view=paginator,
            ephemeral=True,
        )

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
