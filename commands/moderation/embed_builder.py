"""Embed builder - mod tool to create and post custom embeds."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod


def setup(bot, group=None):
    """Register embed builder command."""
    command_decorator = (
        group.command(name="embed_builder", description="Create and post a custom embed (mods only).")
        if group
        else bot.tree.command(name="embed_builder", description="Create and post a custom embed (mods only).")
    )

    @command_decorator
    @app_commands.describe(
        channel="Channel to post the embed in",
        title="Embed title",
        description="Embed description/body",
        color="Embed color (red, green, blue, gold, orange, or a hex code like 0x3498db)",
        footer="Optional footer text",
    )
    async def embed_builder(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        description: str = "",
        color: str = "blue",
        footer: Optional[str] = None,
    ):
        """Create and post a custom embed."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Only moderators can use the embed builder.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        title = (title or "Embed")[:256]
        description = (description or "")[:4096]
        footer = (footer or "")[:2048] if footer else None

        color_map = {
            "red": discord.Color.red(),
            "green": discord.Color.green(),
            "blue": discord.Color.blue(),
            "gold": discord.Color.gold(),
            "orange": discord.Color.orange(),
            "purple": discord.Color.purple(),
        }
        embed_color = color_map.get(color.lower())
        if embed_color is None:
            try:
                if color.startswith("0x") or color.startswith("#"):
                    hex_val = color.lstrip("#")
                    if color.startswith("0x"):
                        hex_val = color[2:]
                    embed_color = discord.Color(int(hex_val, 16))
                else:
                    embed_color = discord.Color.blue()
            except (ValueError, TypeError):
                embed_color = discord.Color.blue()

        embed = obsidian_embed(title, description or "\u200b", color=embed_color, client=interaction.client)
        if footer:
            embed.set_footer(text=footer)

        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "✅ Embed Posted",
                    f"Your embed was posted to {channel.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "I cannot send messages in that channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
