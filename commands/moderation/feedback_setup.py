"""Configure channel for member /feedback."""
from __future__ import annotations

import discord
from discord import app_commands

from core.utils import success_embed, is_mod
from database import set_guild_setting


def setup(bot, group=None):
    command_decorator = (
        group.command(name="feedback_setup", description="Channel where /feedback posts are delivered.")
        if group
        else bot.tree.command(name="feedback_setup", description="Channel where /feedback posts are delivered.")
    )

    @command_decorator
    @app_commands.describe(channel="Staff channel for member feedback")
    async def feedback_setup(interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import reply_mods_only
            return await reply_mods_only(interaction)
        await set_guild_setting(interaction.guild.id, "feedback_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=success_embed(
                "Feedback channel set",
                f"`/feedback` will post to {channel.mention}.",
                client=interaction.client,
            ),
            ephemeral=True,
        )
