"""Lock and unlock channel commands."""
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, error_embed, is_mod
from views import ConfirmView


async def apply_channel_lock(channel: discord.TextChannel, *, actor: discord.Member, lock: bool = True) -> bool:
    """Apply (or undo) the @everyone send-messages lock on ``channel``.

    Extracted from the slash callback so dashboard quick-actions can reuse it
    without duplicating the overwrite math.
    """
    if not isinstance(channel, discord.TextChannel) or not channel.guild:
        return False
    overwrites = dict(channel.overwrites)
    default_role = channel.guild.default_role
    current = overwrites.get(default_role, discord.PermissionOverwrite())
    current.send_messages = False if lock else None
    overwrites[default_role] = current
    reason = f"Channel {'locked' if lock else 'unlocked'} by {actor}"
    await channel.edit(overwrites=overwrites, reason=reason)
    return True


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
                embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in text channels.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Channels** in this server. Ask an admin to grant it.", client=interaction.client),
                ephemeral=True,
            )

        embed = obsidian_embed(
            "⚠️ Confirm Lock",
            f"Lock {interaction.channel.mention}? Only members with overwrites will be able to send messages.",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if not confirmed:
                await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                return
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.followup.send("Only the person who started this can confirm.", ephemeral=True)
                return
            await apply_channel_lock(interaction.channel, actor=interaction.user, lock=True)
            await btn_interaction.followup.send(
                embed=obsidian_embed("🔒 Channel Locked", "Only members with overwrites can send messages. Use `/unlock` to restore.", color=discord.Color.green(), client=interaction.client),
            )
        view = ConfirmView(on_confirm)
        await interaction.response.send_message(embed=embed, view=view)

    @unlock_decorator
    async def unlock(interaction: discord.Interaction):
        """Unlock the current channel."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in text channels.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Channels** in this server. Ask an admin to grant it.", client=interaction.client),
                ephemeral=True,
            )

        await apply_channel_lock(interaction.channel, actor=interaction.user, lock=False)
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔓 Channel Unlocked",
                "Members can send messages again.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
        )

    lock_bulk_decorator = (
        group.command(name="lock_bulk", description="Lock multiple channels in this category (with preview).")
        if group
        else bot.tree.command(name="lock_bulk", description="Lock multiple channels in this category (with preview).")
    )

    @lock_bulk_decorator
    async def lock_bulk(interaction: discord.Interaction):
        """Lock all text channels in the current category with preview and confirmation."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
                ephemeral=True,
            )
        if not isinstance(interaction.channel, discord.TextChannel) or not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in text channels.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.channel.permissions_for(interaction.guild.me).manage_channels:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Channels** in this server.", client=interaction.client),
                ephemeral=True,
            )

        category = interaction.channel.category
        if category:
            channels = [c for c in category.text_channels if isinstance(c, discord.TextChannel)]
        else:
            channels = [c for c in interaction.guild.text_channels if c.category is None]

        if not channels:
            return await interaction.response.send_message(
                embed=error_embed("No Channels", "No text channels to lock in this category.", client=interaction.client),
                ephemeral=True,
            )

        channel_list = "\n".join(f"• {ch.mention}" for ch in channels[:15])
        if len(channels) > 15:
            channel_list += f"\n... and {len(channels) - 15} more"

        embed = obsidian_embed(
            "⚠️ Confirm Bulk Lock",
            f"Lock **{len(channels)}** channel(s)?\n\n{channel_list}\n\nOnly members with overwrites will be able to send messages.",
            color=discord.Color.orange(),
            client=interaction.client,
        )

        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if not confirmed:
                await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                return
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.followup.send("Only the person who started this can confirm.", ephemeral=True)
                return
            locked = 0
            failed = []
            default_role = interaction.guild.default_role
            for ch in channels:
                try:
                    overwrites = dict(ch.overwrites)
                    current = overwrites.get(default_role, discord.PermissionOverwrite())
                    current.send_messages = False
                    overwrites[default_role] = current
                    await ch.edit(overwrites=overwrites, reason=f"Bulk lock by {interaction.user}")
                    locked += 1
                except discord.Forbidden:
                    failed.append(ch.mention)
            msg = f"Locked **{locked}** channel(s)."
            if failed:
                msg += f"\nCould not lock: {', '.join(failed)}"
            await btn_interaction.followup.send(
                embed=obsidian_embed("🔒 Bulk Lock Complete", msg, color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )

        view = ConfirmView(on_confirm)
        await interaction.response.send_message(embed=embed, view=view)
