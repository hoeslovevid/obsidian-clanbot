"""Coinflip command - flip a coin."""
import random
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import obsidian_embed


def setup(bot, group=None):
    """Register the coinflip command."""
    command_decorator = (
        group.command(name="coinflip", description="Flip a coin — heads or tails.")
        if group
        else bot.tree.command(name="coinflip", description="Flip a coin — heads or tails.")
    )

    @command_decorator
    async def coinflip(interaction: discord.Interaction):
        """Flip a coin and show the result."""
        result = random.choice(("Heads", "Tails"))
        emoji = "🪙" if result == "Heads" else "🔙"
        embed = obsidian_embed(
            f"{emoji} {result}!",
            f"The coin landed on **{result}**.",
            color=discord.Color.gold(),
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed)
