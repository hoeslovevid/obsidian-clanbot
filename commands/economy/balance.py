"""Balance command."""
import discord
from discord import app_commands
import aiosqlite

from utils import obsidian_embed, try_dm_then_ephemeral, feature_off_embed, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD, EMBED_COLORS, bullet_list, format_number, pluralize
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

        # Single connection: balance + total_earned + pets in one go
        balance = 0
        total_earned = 0
        pet_row = None
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
        
        footer = "Use /daily or /leaderboard • /help for all commands"
        if is_new:
            footer = "New here? Use /daily to get started! • /help for commands"
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
