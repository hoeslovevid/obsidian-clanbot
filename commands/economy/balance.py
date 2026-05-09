"""Balance command."""
import discord
from discord import app_commands
import aiosqlite

from core.utils import obsidian_embed, try_dm_then_ephemeral, feature_off_embed, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD, EMBED_COLORS, bullet_list, format_number, pluralize
from database import DB_PATH


def setup(bot, group=None):
    """Register the balance command under economy and as top-level shortcuts."""
    async def balance_callback(interaction: discord.Interaction):
        """Display the user's current coin balance."""
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

        # Single connection: balance + total_earned + pets + daily_claims + recent tx in one go
        balance = 0
        total_earned = 0
        pet_row = None
        next_daily_ts = None
        recent_tx = []
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance, total_earned FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            row = await cur.fetchone()
            if row:
                balance = row[0] or 0
                total_earned = row[1] or 0
            cur2 = await db.execute(
                "SELECT pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            pet_row = await cur2.fetchone()
            cur3 = await db.execute(
                "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            daily_row = await cur3.fetchone()
            cur4 = await db.execute(
                "SELECT amount, transaction_type, description, created_at FROM economy_transactions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 3",
                (interaction.guild.id, interaction.user.id),
            )
            recent_tx = await cur4.fetchall()
        if daily_row:
            from datetime import datetime, timezone, timedelta
            today = datetime.now(timezone.utc).date().isoformat()
            if daily_row[0] == today:
                next_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                next_daily_ts = int(next_dt.timestamp())

        is_new = balance == 0 and total_earned == 0

        # Compact layout with progress bar (visual bar for balance, capped at 100k display)
        bar_max = 100_000
        pct = min(100, int(100 * balance / bar_max)) if bar_max > 0 else 0
        bar_len = 10
        filled = int(bar_len * pct / 100)
        bar_str = "█" * filled + "░" * (bar_len - filled)

        earning_items = [
            f"`/economy daily` – {format_number(COINS_DAILY_REWARD)} coins/day",
            f"Messages – {COINS_PER_MESSAGE} {pluralize(COINS_PER_MESSAGE, 'coin')} ({MESSAGE_COOLDOWN_SECONDS}s cooldown)",
            f"Voice – {COINS_PER_MINUTE_VOICE} coins/minute",
        ]
        fields = [
            ("💰 Balance", f"**{format_number(balance)}** {pluralize(balance, 'coin')}\n`[{bar_str}]` {pct}%", True),
            ("📊 Earning Methods", bullet_list(earning_items), False)
        ]

        if pet_row:
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR
            pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at = pet_row
            h = _apply_decay(hunger or 100, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            hp = _apply_decay(happiness or 100, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)
            fields.insert(1, ("🐾 Pet", f"{pet_name or pet_type}: Hunger {h}%, Happiness {hp}%", True))

        # Active investment summary
        inv_field = None
        async with aiosqlite.connect(DB_PATH) as db:
            cur_inv = await db.execute(
                "SELECT amount, interest_rate, maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 ORDER BY invested_at DESC LIMIT 1",
                (interaction.guild.id, interaction.user.id),
            )
            inv_row = await cur_inv.fetchone()
        if inv_row:
            from datetime import datetime, timezone as _tz
            inv_amt, inv_rate, inv_maturity_str = inv_row
            inv_return = int(inv_amt * (1 + inv_rate))
            try:
                inv_mat = datetime.fromisoformat(inv_maturity_str.replace("Z", "+00:00"))
                mat_ts = int(inv_mat.timestamp())
                now_dt = datetime.now(_tz.utc)
                if now_dt >= inv_mat:
                    inv_status = "✅ **Ready to collect!** Use `/economy invest_collect`"
                else:
                    inv_status = f"⏳ Matures <t:{mat_ts}:R>"
            except Exception:
                inv_status = "⏳ Maturing…"
            inv_field = (
                "📈 Active Investment",
                f"**{format_number(inv_amt)}** → **{format_number(inv_return)}** (+{int(inv_rate*100)}%)\n{inv_status}",
                True,
            )

        if recent_tx:
            tx_lines = []
            for amt, txn_type, desc, created in recent_tx:
                sign = "+" if amt > 0 else ""
                tx_lines.append(f"{sign}{format_number(amt)} — {desc[:30]}{'…' if desc and len(desc) > 30 else ''}")
            fields.append(("📜 Recent", "\n".join(tx_lines), True))

        if inv_field:
            fields.append(inv_field)

        footer = "Use /daily or /leaderboard • Right-click user → Transfer Coins"
        if is_new:
            footer = "New here? Use /daily to get started! • /help for commands"
        elif next_daily_ts:
            footer = f"Next daily: <t:{next_daily_ts}:R> • Right-click user → Transfer Coins"
        embed = obsidian_embed(
            "💰 Coin Balance",
            "",
            color=EMBED_COLORS["economy"],
            author=interaction.user,
            thumbnail=interaction.user.display_avatar.url if hasattr(interaction.user, 'display_avatar') else interaction.user.avatar.url if interaction.user.avatar else None,
            fields=fields,
            footer=footer,
            client=interaction.client,
        )
        await try_dm_then_ephemeral(interaction.user, embed, interaction, ephemeral_message="I couldn't DM you. Here's your balance:")

    group.command(name="balance", description="View your coin balance.")(balance_callback)
    group.command(name="bal", description="View your coin balance (alias).")(balance_callback)
    # Top-level shortcuts
    for name in ("balance", "bal"):
        shortcut = app_commands.Command(name=name, description=f"View your coin balance (shortcut for /economy {name})", callback=balance_callback)
        bot.tree.add_command(shortcut)
