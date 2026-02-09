"""Purge command."""
import asyncio
import discord  # type: ignore
from discord import app_commands  # type: ignore

from utils import obsidian_embed, is_mod
from views import ConfirmView


def setup(bot, group=None):
    """Register the purge command."""
    command_decorator = group.command(name="purge", description="Delete messages (1–100 or 'all') from this channel.") if group else bot.tree.command(name="purge", description="Delete messages (1–100 or 'all') from this channel.")
    
    @command_decorator
    @app_commands.describe(
        amount="Number of messages to delete (1-100), or 'all' to delete all messages in channel"
    )
    async def purge(interaction: discord.Interaction, amount: str):
        # Check if user is a mod
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)

        # Check if channel is a text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("This command can only be used in text channels.", ephemeral=True)

        # Parse amount
        if amount.lower() == "all":
            limit = None  # We'll use a high number for "all"
            delete_count = 9999  # Discord API limits to 100 per call, but we'll loop
        else:
            try:
                limit = int(amount)
                if limit < 1:
                    return await interaction.response.send_message("Amount must be at least 1.", ephemeral=True)
                if limit > 100:
                    return await interaction.response.send_message("Amount cannot exceed 100 per command. Use the command multiple times or use 'all'.", ephemeral=True)
                delete_count = limit
            except ValueError:
                return await interaction.response.send_message("Invalid amount. Use a number (1-100) or 'all'.", ephemeral=True)

        # Check bot permissions
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            return await interaction.response.send_message(
                "I need **Manage Messages** in this channel. Ask an admin to grant it.",
                ephemeral=True,
            )

        # Confirmation for large purges
        needs_confirm = amount.lower() == "all" or (amount.lower() != "all" and int(amount) >= 10)
        if needs_confirm:
            preview = "all messages" if amount.lower() == "all" else f"{amount} messages"
            embed = obsidian_embed(
                "⚠️ Confirm Purge",
                f"Delete **{preview}** from {interaction.channel.mention}?\n\nThis cannot be undone.",
                color=discord.Color.orange(),
                client=interaction.client,
            )
            async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
                if not confirmed:
                    await btn_interaction.response.send_message("Cancelled.", ephemeral=True)
                    return
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.response.send_message("Only the person who started this can confirm.", ephemeral=True)
                    return
                await btn_interaction.response.defer(ephemeral=True)
                deleted = 0
                try:
                    if amount.lower() == "all":
                        while True:
                            try:
                                msgs = await interaction.channel.purge(limit=100, check=lambda m: not m.pinned)
                            except discord.HTTPException as e:
                                if e.status == 429:
                                    await asyncio.sleep(getattr(e, "retry_after", 1))
                                    continue
                                raise
                            if not msgs:
                                break
                            deleted += len(msgs)
                    else:
                        msgs = await interaction.channel.purge(limit=int(amount), check=lambda m: not m.pinned)
                        deleted = len(msgs)
                    if deleted == 0:
                        await btn_interaction.followup.send("No messages were deleted. (Pinned messages are not deleted)", ephemeral=True)
                    else:
                        await btn_interaction.followup.send(
                            embed=obsidian_embed("Messages Purged", f"Deleted **{deleted}** message(s) from {interaction.channel.mention}.", color=discord.Color.green(), client=interaction.client),
                            ephemeral=True,
                        )
                except discord.Forbidden:
                    await btn_interaction.followup.send("I need **Manage Messages** in this channel.", ephemeral=True)
                except Exception as e:
                    await btn_interaction.followup.send(f"Error: {e}", ephemeral=True)

            view = ConfirmView(on_confirm)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        # Small purge: no confirmation
        await interaction.response.defer(ephemeral=True)
        deleted = 0
        try:
            if amount.lower() == "all":
                # Delete in batches of 100 (Discord API limit)
                # No manual sleep - discord.py handles rate limits; retry on 429
                while True:
                    try:
                        deleted_messages = await interaction.channel.purge(limit=100, check=lambda m: not m.pinned)
                    except discord.HTTPException as e:
                        if e.status == 429:
                            wait = getattr(e, "retry_after", None) or 1.0
                            await asyncio.sleep(wait)
                            continue
                        raise
                    if not deleted_messages:
                        break
                    deleted += len(deleted_messages)
            else:
                # Delete specified amount
                deleted_messages = await interaction.channel.purge(limit=limit, check=lambda m: not m.pinned)
                deleted = len(deleted_messages)

            if deleted == 0:
                await interaction.followup.send("No messages were deleted. (Note: Pinned messages are not deleted)", ephemeral=True)
            else:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "Messages Purged",
                        f"Successfully deleted **{deleted}** message(s) from {interaction.channel.mention}.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.followup.send("I need **Manage Messages** in this channel. Ask an admin to grant it.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"An error occurred while deleting messages: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Unexpected error: {e}", ephemeral=True)
