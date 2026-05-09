"""Purge command."""
import asyncio
import io
from datetime import datetime, timezone
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, error_embed, is_mod, format_number, pluralize, permission_hint_embed
from views import ConfirmView


def _build_purge_transcript(messages: list) -> str:
    """Build a text transcript of messages for soft-delete archive."""
    lines = []
    for m in reversed(messages):
        ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "?"
        author = getattr(m.author, "display_name", str(m.author)) if m.author else "Unknown"
        content = (m.content or "").replace("\n", " ")[:200]
        if len((m.content or "")) > 200:
            content += "..."
        lines.append(f"[{ts}] {author}: {content}")
    return "\n".join(lines) or "(no content)"


def setup(bot, group=None):
    """Register the purge command."""
    command_decorator = group.command(name="purge", description="Delete messages (1–100 or 'all') from this channel.") if group else bot.tree.command(name="purge", description="Delete messages (1–100 or 'all') from this channel.")

    @command_decorator
    @app_commands.choices(amount=[
        app_commands.Choice(name="10 messages", value="10"),
        app_commands.Choice(name="25 messages", value="25"),
        app_commands.Choice(name="50 messages", value="50"),
        app_commands.Choice(name="100 messages", value="100"),
        app_commands.Choice(name="All (unpinned)", value="all"),
    ])
    @app_commands.describe(
        amount="Number of messages to delete, or all",
        archive="Save a transcript before deleting (default: yes)",
    )
    async def purge(interaction: discord.Interaction, amount: app_commands.Choice[str], archive: bool = True):
        # Check if user is a mod
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Sorry, but you are not an Administrator in this server.", client=interaction.client),
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in a server.", client=interaction.client),
                ephemeral=True,
            )

        # Check if channel is a text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "This command can only be used in text channels.", client=interaction.client),
                ephemeral=True
            )

        # Parse amount
        amount_val = amount.value if hasattr(amount, "value") else str(amount)
        if amount_val.lower() == "all":
            limit = None
            delete_count = 9999
        else:
            try:
                limit = int(amount_val)
                if limit < 1:
                    return await interaction.response.send_message(
                        embed=error_embed("Invalid Amount", "Amount must be at least 1.", client=interaction.client),
                        ephemeral=True
                    )
                if limit > 100:
                    return await interaction.response.send_message(
                        embed=error_embed("Invalid Amount", "Amount cannot exceed 100 per command. Use the command multiple times or use 'all'.", client=interaction.client),
                        ephemeral=True
                    )
                delete_count = limit
            except ValueError:
                return await interaction.response.send_message(
                    embed=error_embed("Invalid Amount", "Use a number (1-100) or 'all'.", client=interaction.client),
                    ephemeral=True
                )

        # Check bot permissions
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Messages** in this channel. Ask an admin to grant it.", client=interaction.client),
                ephemeral=True,
            )

        # Always require confirmation
        needs_confirm = True
        if needs_confirm:
            preview = "all unpinned messages" if amount_val.lower() == "all" else f"up to {amount_val} messages"
            archive_note = " A transcript will be saved." if archive else ""
            embed = obsidian_embed(
                "⚠️ Confirm Purge",
                f"Delete **{preview}** from {interaction.channel.mention}?{archive_note}\n\nThis cannot be undone.",
                color=discord.Color.orange(),
                footer="Mod only • See also: /mod warn, /mod data_retention",
                client=interaction.client,
            )
            async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
                if not confirmed:
                    await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                    return
                if btn_interaction.user.id != interaction.user.id:
                    await btn_interaction.followup.send("Only the person who started this can confirm.", ephemeral=True)
                    return
                # ConfirmView already responded with edit_message; use followup for results
                processing_embed = obsidian_embed(
                    "⏳ Processing Purge",
                    "Deleting messages... This may take a moment for large batches.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                )
                try:
                    await btn_interaction.edit_original_response(embed=processing_embed, view=None)
                except Exception:
                    pass
                transcript_file = None
                try:
                    deleted_msgs = []
                    if amount_val.lower() == "all":
                        while True:
                            try:
                                msgs = await interaction.channel.purge(limit=100, check=lambda m: not m.pinned)
                            except discord.HTTPException as e:
                                if e.status == 429:
                                    retry_after = getattr(e, "retry_after", 1.5)
                                    await asyncio.sleep(float(retry_after))
                                    continue
                                raise
                            deleted_msgs.extend(msgs)
                            if not msgs:
                                break
                            # Proactive delay between batches to avoid Discord rate limits (5 bulk deletes per 5s)
                            await asyncio.sleep(1.1)
                    else:
                        for attempt in range(3):
                            try:
                                deleted_msgs = await interaction.channel.purge(limit=int(amount_val), check=lambda m: not m.pinned)
                                break
                            except discord.HTTPException as e:
                                if e.status == 429 and attempt < 2:
                                    await asyncio.sleep(getattr(e, "retry_after", 1.5))
                                    continue
                                raise
                    if archive and deleted_msgs:
                        transcript = _build_purge_transcript(deleted_msgs)
                        fn = f"purge_{interaction.channel.name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
                        transcript_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=fn)
                    deleted = len(deleted_msgs)
                    if deleted == 0:
                        await btn_interaction.followup.send("No messages were deleted. (Pinned messages are not deleted)", ephemeral=True)
                    else:
                        summary = f"Deleted **{format_number(deleted)}** {pluralize(deleted, 'message')} from {interaction.channel.mention}." + (" Transcript attached." if transcript_file else "")
                        kwargs = {
                            "embed": obsidian_embed("Messages Purged", summary, color=discord.Color.green(), footer="See also: /mod warn, /mod data_retention", client=interaction.client),
                            "ephemeral": True,
                        }
                        if transcript_file:
                            kwargs["file"] = transcript_file
                        await btn_interaction.followup.send(**kwargs)
                    try:
                        from core.audit import log_audit
                        await log_audit(interaction.guild.id, "purge", interaction.user.id, details=f"{deleted} msgs in #{interaction.channel.name}", bot=interaction.client)
                    except Exception:
                        pass
                except discord.Forbidden:
                    await btn_interaction.followup.send(embed=permission_hint_embed("Manage Messages", client=interaction.client), ephemeral=True)
                except Exception as e:
                    await btn_interaction.followup.send(f"Error: {e}", ephemeral=True)

            view = ConfirmView(on_confirm)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
