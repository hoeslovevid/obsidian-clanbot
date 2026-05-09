"""Stash command - store coins for 1% daily interest."""
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED, format_number, EMBED_COLORS
from database import DB_PATH, now_utc, add_coins, remove_coins, get_user_balance
import aiosqlite

STASH_INTEREST_RATE = 0.01  # 1% per day


async def _get_stash(guild_id: int, user_id: int) -> tuple[int, str | None]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT stashed, last_interest_at FROM user_stash WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            return row[0] or 0, row[1]
        return 0, None


async def _apply_interest(guild_id: int, user_id: int) -> int:
    stashed, last_at = await _get_stash(guild_id, user_id)
    if stashed <= 0:
        return stashed
    now = now_utc()
    if last_at:
        try:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            days = (now - last_dt).total_seconds() / 86400
        except Exception:
            days = 0
    else:
        days = 0
    if days >= 1:
        interest = int(stashed * STASH_INTEREST_RATE * min(days, 30))
        if interest > 0:
            stashed += interest
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO user_stash (guild_id, user_id, stashed, last_interest_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(guild_id, user_id) DO UPDATE SET stashed=excluded.stashed, last_interest_at=excluded.last_interest_at""",
                    (guild_id, user_id, stashed, now.isoformat()),
                )
                await db.commit()
    return stashed


def setup(bot, group=None):
    cmd = group.command(name="stash", description="Store coins for 1% daily interest. Deposit or withdraw.") if group else bot.tree.command(name="stash", description="Store coins for 1% daily interest.")

    async def _stash_amount_autocomplete(interaction: discord.Interaction, current: str) -> list:
        from discord import app_commands
        presets = ["100", "500", "1000", "5000", "10000", "all"]
        if not current or current.strip() == "":
            return [app_commands.Choice(name=p, value=p) for p in presets[:25]]
        cur = current.strip().lower()
        matches = [p for p in presets if cur in p.lower() or (cur.isdigit() and p.isdigit() and cur in p)]
        return [app_commands.Choice(name=m, value=m) for m in matches[:25]]

    @cmd
    @app_commands.describe(amount="Amount to deposit or withdraw (e.g. 500, 1000, all)")
    @app_commands.autocomplete(amount=_stash_amount_autocomplete)
    @app_commands.choices(action=[
        app_commands.Choice(name="Deposit", value="deposit"),
        app_commands.Choice(name="Withdraw", value="withdraw"),
        app_commands.Choice(name="Balance", value="balance"),
    ])
    async def stash(interaction: discord.Interaction, action: app_commands.Choice[str], amount: str = "0"):
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        stashed = await _apply_interest(guild_id, user_id)

        act = action.value if hasattr(action, "value") else str(action)
        if act == "balance":
            embed = obsidian_embed(
                "Stash Balance",
                f"You have **{format_number(stashed)}** coins in stash.\n\n_1% interest applied daily (max 30 days)._",
                color=EMBED_COLORS["economy"],
                footer="Use /economy stash deposit/withdraw to manage",
                client=interaction.client,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        try:
            amt_str = str(amount).strip().lower()
            if amt_str == "all":
                amt = stashed if act == "withdraw" else await get_user_balance(guild_id, user_id)
            else:
                amt = int(amount)
        except (ValueError, TypeError):
            return await interaction.followup.send("Invalid amount. Use a number or 'all'.", ephemeral=True)

        if amt <= 0:
            return await interaction.followup.send("Amount must be positive.", ephemeral=True)

        if act == "deposit":
            bal = await get_user_balance(guild_id, user_id)
            if amt > bal:
                return await interaction.followup.send(f"Not enough coins. Balance: {format_number(bal)}", ephemeral=True)
            await remove_coins(guild_id, user_id, amt, "STASH", "Stashed")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO user_stash (guild_id, user_id, stashed, last_interest_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(guild_id, user_id) DO UPDATE SET stashed=stashed+excluded.stashed, last_interest_at=COALESCE(last_interest_at, excluded.last_interest_at)""",
                    (guild_id, user_id, amt, now_utc().isoformat()),
                )
                await db.commit()
            embed = obsidian_embed("Deposited", f"Stashed **{format_number(amt)}** coins. Earn 1% daily interest.", color=EMBED_COLORS["economy"], client=interaction.client)
        else:
            if amt > stashed:
                return await interaction.followup.send(f"Not enough in stash. Stashed: {format_number(stashed)}", ephemeral=True)
            await add_coins(guild_id, user_id, amt, "STASH", "Withdrew from stash")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE user_stash SET stashed=stashed-? WHERE guild_id=? AND user_id=?",
                    (amt, guild_id, user_id),
                )
                await db.execute("DELETE FROM user_stash WHERE guild_id=? AND user_id=? AND stashed<=0", (guild_id, user_id))
                await db.commit()
            embed = obsidian_embed("Withdrawn", f"Withdrew **{format_number(amt)}** from stash.", color=EMBED_COLORS["economy"], client=interaction.client)
        await interaction.followup.send(embed=embed, ephemeral=True)
