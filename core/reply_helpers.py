"""Consistent user-facing error and context replies (professional polish)."""
from __future__ import annotations

import discord

from core.utils import error_embed, obsidian_embed


def server_only_embed(client=None) -> discord.Embed:
    return error_embed(
        "Server only",
        "This command can only be used inside a server.",
        action_hint="Join a server where Obsidian Bot is installed and try again.",
        client=client,
    )


def mods_only_embed(client=None) -> discord.Embed:
    return error_embed(
        "Moderators only",
        "You need administrator or moderator permissions to use this.",
        client=client,
    )


async def reply_server_only(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        embed=server_only_embed(interaction.client),
        ephemeral=True,
    )


async def reply_mods_only(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        embed=mods_only_embed(interaction.client),
        ephemeral=True,
    )


async def reply_not_found(interaction: discord.Interaction, what: str) -> None:
    await interaction.response.send_message(
        embed=error_embed("Not found", what, client=interaction.client),
        ephemeral=True,
    )


async def deny_server_only(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    """Branded server-only reply (works after defer)."""
    embed = server_only_embed(interaction.client)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


async def deny_mods_only(interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
    embed = mods_only_embed(interaction.client)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
