"""Lock and unlock channel commands."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import obsidian_embed, is_mod


def setup(bot, group=None):
    """Register lock and unlock commands."""
    lock_decorator = (
        group.command(name="lock", description="Lock channel — prevent @everyone from sending messages.")
        if group
        else bot.tree.command(name="lock", description="Lock channel — prevent @everyone from sending messages.")
    )
    unlock_decorator = (
        group.command(name="unlock", description="Unlock channel — restore sending for @everyone.")
        if group
        else bot.tree.command(name="unlock", description="Unlock channel — restore sending for @everyone.")
    )

    @lock_decorator
    async def lock(interaction: discord.Interaction):
        """Lock the current channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                "This command can only be used in text channels.",
                ephemeral=True,
            )
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            return await interaction.response.send_message(
                "I don't have permission to manage this channel.",
                ephemeral=True,
            )

        overwrites = dict(interaction.channel.overwrites)
        default_role = interaction.guild.default_role
        current = overwrites.get(default_role, discord.PermissionOverwrite())
        current.send_messages = False
        overwrites[default_role] = current

        await interaction.channel.edit(
            overwrites=overwrites,
            reason=f"Channel locked by {interaction.user}",
        )
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔒 Channel Locked",
                "Only members with overwrites can send messages. Use `/unlock` to restore.",
                color=discord.Color.orange(),
                client=interaction.client,
            ),
        )

    @unlock_decorator
    async def unlock(interaction: discord.Interaction):
        """Unlock the current channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                "This command can only be used in text channels.",
                ephemeral=True,
            )
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            return await interaction.response.send_message(
                "I don't have permission to manage this channel.",
                ephemeral=True,
            )

        overwrites = dict(interaction.channel.overwrites)
        default_role = interaction.guild.default_role
        current = overwrites.get(default_role, discord.PermissionOverwrite())
        current.send_messages = None  # Restore to default (allow)
        overwrites[default_role] = current

        await interaction.channel.edit(
            overwrites=overwrites,
            reason=f"Channel unlocked by {interaction.user}",
        )
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔓 Channel Unlocked",
                "Members can send messages again.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
        )
