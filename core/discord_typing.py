"""Shared discord.py typing helpers for Pyright-safe access patterns."""
from __future__ import annotations

from typing import Optional, TypeVar, cast

import discord
from discord import app_commands

T = TypeVar("T")


def voice_client(guild: discord.Guild) -> discord.VoiceClient | None:
    """Return a concrete VoiceClient, not VoiceProtocol."""
    vc = guild.voice_client
    return vc if isinstance(vc, discord.VoiceClient) else None


def set_voice_source_volume(vc: discord.VoiceClient, volume: float) -> None:
    source = vc.source
    if isinstance(source, discord.PCMVolumeTransformer):
        source.volume = volume


async def fetch_text_message(
    channel: discord.abc.Messageable | None,
    message_id: int,
) -> discord.Message | None:
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None
    try:
        return await channel.fetch_message(message_id)
    except discord.NotFound:
        return None


async def fetch_interaction_message(
    interaction: discord.Interaction,
    message_id: int,
) -> discord.Message | None:
    return await fetch_text_message(interaction.channel, message_id)


def set_view_controls_disabled(view: discord.ui.View, *, disabled: bool) -> None:
    for item in view.children:
        if isinstance(item, (discord.ui.Button, discord.ui.Select)):
            item.disabled = disabled


def guild_channel_id(channel: discord.abc.GuildChannel | discord.Thread | None) -> int | None:
    if isinstance(channel, (discord.abc.GuildChannel, discord.Thread)):
        return channel.id
    return None


def choice_value(choice: app_commands.Choice[T] | None) -> T | None:
    return choice.value if choice is not None else None


def require_guild(interaction: discord.Interaction) -> discord.Guild | None:
    return interaction.guild


def require_member(interaction: discord.Interaction) -> discord.Member | None:
    user = interaction.user
    return user if isinstance(user, discord.Member) else None


def require_member_voice_channel(member: discord.Member) -> discord.VoiceChannel | None:
    voice = member.voice
    if voice and isinstance(voice.channel, discord.VoiceChannel):
        return voice.channel
    return None


def voice_channel_from_vc(vc: discord.VoiceClient | None) -> discord.VoiceChannel | None:
    if not vc:
        return None
    channel = vc.channel
    return channel if isinstance(channel, discord.VoiceChannel) else None


def purgeable_channel(
    channel: discord.abc.GuildChannel | discord.Thread | None,
) -> discord.TextChannel | discord.Thread | None:
    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        return channel
    return None


def text_channel_label(channel: discord.TextChannel | discord.Thread) -> str:
    return f"#{channel.name}" if isinstance(channel, discord.TextChannel) else channel.name


def text_channel_mention(channel: discord.TextChannel | discord.Thread) -> str:
    return channel.mention if isinstance(channel, discord.TextChannel) else f"#{channel.name}"
