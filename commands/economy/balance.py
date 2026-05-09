"""Balance command."""
import discord
from discord import app_commands
from typing import Optional
import aiosqlite

from core.utils import obsidian_embed, try_dm_then_ephemeral, feature_off_embed, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD, EMBED_COLORS, bullet_list, format_number, pluralize, render_bar
from database import DB_PATH


def setup(bot, group=None):
    """Register the balance command under economy and as top-level shortcuts."""

    @app_commands.describe(
        user="View another member's balance (public). Leave blank for your own (private).",
    )
    async def balance_callback(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        """Display a user's current coin balance."""
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

        target = user or interaction.user
        is_self = target.id == interaction.user.id
        # Own balance → ephemeral DM attempt. Viewing someone else → public.
        await interaction.response.defer(ephemeral=is_self)

        balance = 0
        total_earned = 0
        pet_row = None
        next_daily_ts = None
        recent_tx = []

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT balance, total_earned FROM user_balances WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, target.id),
            )
            row = await cur.fetchone()
            if row:
                balance = row[0] or 0
                total_earned = row[1] or 0

            cur2 = await db.execute(
                "SELECT pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, target.id),
            )
            pet_row = await cur2.fetchone()

            if is_self:
                cur3 = await db.execute(
                    "SELECT last_claim_date FROM daily_claims WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, target.id),
                )
                daily_row = await cur3.fetchone()
                if daily_row:
                    from datetime import datetime, timezone, timedelta
                    today = datetime.now(timezone.utc).date().isoformat()
                    if daily_row[0] == today:
                        next_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                        next_daily_ts = int(next_dt.timestamp())

                cur4 = await db.execute(
                    "SELECT amount, transaction_type, description, created_at FROM economy_transactions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 3",
                    (interaction.guild.id, target.id),
                )
                recent_tx = await cur4.fetchall()

        is_new = balance == 0 and total_earned == 0

        # Visual balance bar capped at 100k for display
        bar_max = 100_000
        pct = min(100, int(100 * balance / bar_max)) if bar_max > 0 else 0

        fields = [
            (
                "💰 Balance",
                f"> **{format_number(balance)}** {pluralize(balance, 'coin')}\n"
                f"{render_bar(pct)}\n"
                f"-# Total earned: {format_number(total_earned)} coins",
                True,
            ),
        ]

        # Earning methods — only shown on own balance to keep it concise
        if is_self and is_new:
            earning_items = [
                f"`/economy daily` – {format_number(COINS_DAILY_REWARD)} coins/day",
                f"Messages – {COINS_PER_MESSAGE} {pluralize(COINS_PER_MESSAGE, 'coin')} ({MESSAGE_COOLDOWN_SECONDS}s cooldown)",
                f"Voice – {COINS_PER_MINUTE_VOICE} coins/minute",
            ]
            fields.append(("📊 Earning Methods", bullet_list(earning_items), False))

        # Pet field — urgency-aware display
        if pet_row:
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR
            pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at = pet_row
            h  = _apply_decay(hunger or 100, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            hp = _apply_decay(happiness or 100, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)

            hunger_icon  = "🚨" if h  < 25 else "⚠️" if h  < 50 else "✅"
            happy_icon   = "🚨" if hp < 25 else "⚠️" if hp < 50 else "😊"
            needs_care   = h < 50 or hp < 50
            pet_label    = f"🐾 Pet {'— needs attention!' if needs_care else ''}"
            nudge        = "\n-# Use `/economy pets feed` or `play` to restore stats." if needs_care else ""

            fields.insert(1, (
                pet_label,
                f"**{pet_name or pet_type}** ({pet_type})\n"
                f"Hunger: {h}/100 {hunger_icon}  ·  Happiness: {hp}/100 {happy_icon}"
                f"{nudge}",
                True,
            ))

        # Active investment summary
        async with aiosqlite.connect(DB_PATH) as db:
            cur_inv = await db.execute(
                "SELECT amount, interest_rate, maturity_date FROM investments WHERE guild_id=? AND user_id=? AND collected=0 ORDER BY invested_at DESC LIMIT 1",
                (interaction.guild.id, target.id),
            )
            inv_row = await cur_inv.fetchone()

        if inv_row:
            from datetime import datetime, timezone as _tz
            inv_amt, inv_rate, inv_maturity_str = inv_row
            inv_return = int(inv_amt * (1 + inv_rate))
            try:
                inv_mat = datetime.fromisoformat(inv_maturity_str.replace("Z", "+00:00"))
                mat_ts  = int(inv_mat.timestamp())
                if datetime.now(_tz.utc) >= inv_mat:
                    inv_status = "✅ **Ready to collect!** Use `/economy invest_collect`"
                else:
                    inv_status = f"⏳ Matures <t:{mat_ts}:R>"
            except Exception:
                inv_status = "⏳ Maturing…"
            fields.append((
                "📈 Active Investment",
                f"**{format_number(inv_amt)}** → **{format_number(inv_return)}** (+{int(inv_rate*100)}%)\n{inv_status}",
                True,
            ))

        # Recent transactions (self only — privacy)
        if is_self and recent_tx:
            tx_lines = []
            for amt, txn_type, desc, created in recent_tx:
                sign = "+" if amt > 0 else ""
                tx_lines.append(f"{sign}{format_number(amt)} — {desc[:30]}{'…' if desc and len(desc) > 30 else ''}")
            fields.append(("📜 Recent", "\n".join(tx_lines), True))

        footer = "Use /daily or /leaderboard • Right-click user → Transfer Coins"
        if is_new and is_self:
            footer = "New here? Use /daily to get started! • /help for commands"
        elif next_daily_ts:
            footer = f"Next daily: <t:{next_daily_ts}:R> • Right-click user → Transfer Coins"

        owner = "Your" if is_self else f"{target.display_name}'s"
        embed = obsidian_embed(
            f"💰 {owner} Balance",
            "",
            color=EMBED_COLORS["economy"],
            author=target,
            thumbnail=target.display_avatar.url if hasattr(target, "display_avatar") else (target.avatar.url if target.avatar else None),
            fields=fields,
            footer=footer,
            client=interaction.client,
        )

        if is_self:
            await try_dm_then_ephemeral(interaction.user, embed, interaction, ephemeral_message="I couldn't DM you. Here's your balance:")
        else:
            await interaction.followup.send(embed=embed)

    group.command(name="balance", description="View your or another member's coin balance.")(balance_callback)
    group.command(name="bal", description="View your or another member's coin balance (alias).")(balance_callback)
    # Top-level shortcuts
    for name in ("balance", "bal"):
        shortcut = app_commands.Command(name=name, description=f"View coin balance (shortcut for /economy {name})", callback=balance_callback)
        bot.tree.add_command(shortcut)
