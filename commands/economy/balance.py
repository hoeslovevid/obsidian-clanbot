"""Balance command."""
import discord

from utils import obsidian_embed, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE, COINS_DAILY_REWARD


def setup(bot):
    """Register the balance command."""
    @bot.tree.command(name="balance", description="Check your coin balance.")
    async def balance(interaction: discord.Interaction):
        """Display the user's current coin balance."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import get_user_balance
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message("Economy system is disabled.", ephemeral=True)
        
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        embed = obsidian_embed(
            "💰 Coin Balance",
            f"You have **{balance:,}** coins.\n\n"
            f"Earn coins by:\n"
            f"• `/daily` - Claim {COINS_DAILY_REWARD:,} coins once per day\n"
            f"• Sending messages ({COINS_PER_MESSAGE} coins per message, {MESSAGE_COOLDOWN_SECONDS}s cooldown)\n"
            f"• Being active in voice channels ({COINS_PER_MINUTE_VOICE} coins per minute)",
            color=discord.Color.gold(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
