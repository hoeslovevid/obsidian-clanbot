"""Ping command - check bot latency."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import obsidian_embed


def setup(bot, group=None):
    """Register the ping command."""
    command_decorator = (
        group.command(name="ping", description="Check bot latency (ms).")
        if group
        else bot.tree.command(name="ping", description="Check bot latency (ms).")
    )

    @command_decorator
    async def ping(interaction: discord.Interaction):
        """Return bot latency in milliseconds."""
        latency_ms = round(interaction.client.latency * 1000, 2)
        if latency_ms < 100:
            color = discord.Color.green()
        elif latency_ms < 250:
            color = discord.Color.gold()
        else:
            color = discord.Color.orange()
        embed = obsidian_embed(
            "🏓 Pong!",
            f"**Websocket Latency:** {latency_ms}ms",
            color=color,
            footer="Latency to Discord servers • Green=good, Yellow=ok, Orange=high",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
