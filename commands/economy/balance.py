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
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        balance = await get_user_balance(interaction.guild.id, interaction.user.id)
        
        fields = [
            ("💰 Balance", f"**{balance:,}** coins", True),
            ("📊 Earning Methods", 
             f"• `/daily` - {COINS_DAILY_REWARD:,} coins/day\n"
             f"• Messages - {COINS_PER_MESSAGE} coins ({MESSAGE_COOLDOWN_SECONDS}s cooldown)\n"
             f"• Voice - {COINS_PER_MINUTE_VOICE} coins/minute", 
             False)
        ]
        
        embed = obsidian_embed(
            "💰 Coin Balance",
            "",
            color=discord.Color.gold(),
            author=interaction.user,
            thumbnail=interaction.user.display_avatar.url if hasattr(interaction.user, 'display_avatar') else interaction.user.avatar.url if interaction.user.avatar else None,
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
