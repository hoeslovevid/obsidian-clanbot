"""Balance command."""
import discord
import aiosqlite

from utils import obsidian_embed, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD
from database import DB_PATH


def setup(bot, group=None):
    """Register the balance and bal (alias) commands."""
    async def balance_callback(interaction: discord.Interaction):
        """Display the user's current coin balance."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import get_user_balance
        
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
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)

        fields = [
            ("💰 Balance", f"**{balance:,}** coins", True),
            ("📊 Earning Methods",
             f"• `/daily` - {COINS_DAILY_REWARD:,} coins/day\n"
             f"• Messages - {COINS_PER_MESSAGE} coins ({MESSAGE_COOLDOWN_SECONDS}s cooldown)\n"
             f"• Voice - {COINS_PER_MINUTE_VOICE} coins/minute",
             False)
        ]

        pet_row = None
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at FROM pets WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id),
            )
            pet_row = await cur.fetchone()
        if pet_row:
            from commands.economy.pets import _apply_decay, HUNGER_DECAY_PER_HOUR, HAPPINESS_DECAY_PER_HOUR
            pet_type, pet_name, hunger, happiness, last_fed_at, last_played_at, created_at = pet_row
            h = _apply_decay(hunger or 100, last_fed_at, created_at, HUNGER_DECAY_PER_HOUR)
            hp = _apply_decay(happiness or 100, last_played_at, created_at, HAPPINESS_DECAY_PER_HOUR)
            fields.insert(1, ("🐾 Pet", f"{pet_name or pet_type}: Hunger {h}%, Happiness {hp}%", True))
        
        embed = obsidian_embed(
            "💰 Coin Balance",
            "",
            color=discord.Color.gold(),
            author=interaction.user,
            thumbnail=interaction.user.display_avatar.url if hasattr(interaction.user, 'display_avatar') else interaction.user.avatar.url if interaction.user.avatar else None,
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    command_decorator = group.command(name="balance", description="View your coin balance.") if group else bot.tree.command(name="balance", description="View your coin balance.")
    command_decorator(balance_callback)

    alias_decorator = group.command(name="bal", description="View your coin balance (alias for balance).") if group else bot.tree.command(name="bal", description="View your coin balance (alias for balance).")
    alias_decorator(balance_callback)
