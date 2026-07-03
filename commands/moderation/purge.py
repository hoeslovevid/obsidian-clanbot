"""Purge command."""
import asyncio
import io
from datetime import datetime, timezone, timedelta
from typing import Optional
import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.embed_templates import confirm_embed
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
        channel = interaction.channel

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
        if not channel.permissions_for(interaction.guild.me).manage_messages:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Messages** in this channel. Ask an admin to grant it.", client=interaction.client),
                ephemeral=True,
            )

        # Always require confirmation
        needs_confirm = True
        if needs_confirm:
            preview = "all unpinned messages" if amount_val.lower() == "all" else f"up to {amount_val} messages"
            archive_note = " A transcript will be saved." if archive else ""
            embed = confirm_embed(
                "⚠️ Confirm Purge",
                f"Delete **{preview}** from {channel.mention}?{archive_note}\n\nThis cannot be undone.",
                footer_key="moderation_purge",
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
                                msgs = await channel.purge(limit=100, check=lambda m: not m.pinned)
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
                                deleted_msgs = await channel.purge(limit=int(amount_val), check=lambda m: not m.pinned)
                                break
                            except discord.HTTPException as e:
                                if e.status == 429 and attempt < 2:
                                    await asyncio.sleep(getattr(e, "retry_after", 1.5))
                                    continue
                                raise
                    if archive and deleted_msgs:
                        transcript = _build_purge_transcript(deleted_msgs)
                        fn = f"purge_{channel.name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
                        transcript_file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=fn)
                    deleted = len(deleted_msgs)
                    if deleted == 0:
                        await btn_interaction.followup.send("No messages were deleted. (Pinned messages are not deleted)", ephemeral=True)
                    else:
                        summary = f"Deleted **{format_number(deleted)}** {pluralize(deleted, 'message')} from {channel.mention}." + (" Transcript attached." if transcript_file else "")
                        kwargs = {
                            "embed": obsidian_embed("Messages Purged", summary, color=discord.Color.green(), footer="See also: /mod warn, /mod data_retention", client=interaction.client),
                            "ephemeral": True,
                        }
                        if transcript_file:
                            kwargs["file"] = transcript_file
                        await btn_interaction.followup.send(**kwargs)
                    try:
                        from core.audit import log_audit
                        await log_audit(interaction.guild.id, "purge", interaction.user.id, details=f"{deleted} msgs in #{channel.name}", bot=interaction.client)
                    except Exception:
                        pass
                except discord.Forbidden:
                    await btn_interaction.followup.send(embed=permission_hint_embed("Manage Messages", client=interaction.client), ephemeral=True)
                except Exception as e:
                    await btn_interaction.followup.send(f"Error: {e}", ephemeral=True)

            view = ConfirmView(on_confirm)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # --- Filtered purge (Item 42) ----------------------------------------------------
    filter_decorator = group.command(
        name="purge_filter",
        description="Delete messages matching user/text/age/bot filters (mods only)."
    ) if group else bot.tree.command(
        name="purge_filter",
        description="Delete messages matching user/text/age/bot filters (mods only).",
    )

    @filter_decorator
    @app_commands.describe(
        limit="How many recent messages to scan (default 100, max 500)",
        user="Only delete messages from this user",
        contains="Only delete messages containing this text (case-insensitive)",
        older_than_hours="Only delete messages older than this many hours",
        from_bots="Only delete bot messages (True) or only humans (False); omit for both",
    )
    async def purge_filter(
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 500] = 100,
        user: Optional[discord.Member] = None,
        contains: Optional[str] = None,
        older_than_hours: Optional[app_commands.Range[int, 0, 24 * 90]] = None,
        from_bots: Optional[bool] = None,
    ):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Administrators only.", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Context", "Run this in a server text channel.", client=interaction.client),
                ephemeral=True,
            )
        channel = interaction.channel
        if not channel.permissions_for(interaction.guild.me).manage_messages:
            return await interaction.response.send_message(
                embed=error_embed("Missing Permissions", "I need **Manage Messages** in this channel.", client=interaction.client),
                ephemeral=True,
            )
        # At least one filter must be set to avoid surprise mass deletes.
        if user is None and not contains and older_than_hours is None and from_bots is None:
            return await interaction.response.send_message(
                embed=error_embed(
                    "No filters set",
                    "Provide at least one filter (user / contains / older_than_hours / from_bots).",
                    action_hint="Use `/mod purge` for a plain bulk delete.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        contains_lower = (contains or "").lower().strip()
        age_cutoff = None
        if older_than_hours is not None:
            age_cutoff = datetime.now(timezone.utc) - timedelta(hours=int(older_than_hours))
        fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)

        def _matches(m: discord.Message) -> bool:
            if m.pinned:
                return False
            if user is not None and m.author.id != user.id:
                return False
            if from_bots is True and not m.author.bot:
                return False
            if from_bots is False and m.author.bot:
                return False
            if contains_lower and contains_lower not in (m.content or "").lower():
                return False
            if age_cutoff is not None and (m.created_at or datetime.now(timezone.utc)) > age_cutoff:
                return False
            return True

        # Scan and collect candidates BEFORE deleting so we can show a preview.
        matched: list[discord.Message] = []
        try:
            async for m in channel.history(limit=int(limit)):
                if _matches(m):
                    matched.append(m)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=permission_hint_embed("Manage Messages", client=interaction.client),
                ephemeral=True,
            )

        if not matched:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "No matches",
                    "No messages match those filters in the last "
                    f"{format_number(int(limit))} scanned.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Build preview
        filt_lines = []
        if user:
            filt_lines.append(f"• user = {user.mention}")
        if contains:
            filt_lines.append(f"• contains = `{contains[:80]}`")
        if older_than_hours is not None:
            filt_lines.append(f"• older_than = {older_than_hours}h")
        if from_bots is True:
            filt_lines.append("• from_bots = yes")
        elif from_bots is False:
            filt_lines.append("• from_bots = humans only")

        old_count = sum(1 for m in matched if (m.created_at or datetime.now(timezone.utc)) < fourteen_days_ago)
        preview = obsidian_embed(
            "⚠️ Confirm filtered purge",
            (
                f"About to delete **{format_number(len(matched))}** "
                f"{pluralize(len(matched), 'message')} from {channel.mention}.\n\n"
                + "\n".join(filt_lines)
                + (
                    f"\n\n_{old_count} of these are >14 days old — will be deleted one-by-one "
                    "(slower)._" if old_count else ""
                )
                + "\n\nThis cannot be undone."
            ),
            color=discord.Color.orange(),
            client=interaction.client,
        )

        # Capture matched ids for the confirm closure
        target_ids = {m.id for m in matched}

        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.followup.send(
                    "Only the person who started this can confirm.", ephemeral=True
                )
            if not confirmed:
                return await btn_interaction.followup.send("Cancelled.", ephemeral=True)

            # Recollect from history to make sure we have fresh Message objects.
            to_delete: list[discord.Message] = []
            try:
                async for m in channel.history(limit=max(int(limit), 100)):
                    if m.id in target_ids:
                        to_delete.append(m)
            except discord.Forbidden:
                return await btn_interaction.followup.send(
                    embed=permission_hint_embed("Manage Messages", client=interaction.client),
                    ephemeral=True,
                )

            bulk_deletable = [m for m in to_delete if (m.created_at or datetime.now(timezone.utc)) >= fourteen_days_ago]
            single_deletable = [m for m in to_delete if m not in bulk_deletable]
            deleted = 0
            skipped = 0

            # Bulk delete in chunks of 100 (Discord API limit).
            for i in range(0, len(bulk_deletable), 100):
                chunk = bulk_deletable[i : i + 100]
                if len(chunk) == 1:
                    try:
                        await chunk[0].delete()
                        deleted += 1
                    except discord.HTTPException:
                        skipped += 1
                    continue
                try:
                    await channel.delete_messages(chunk)
                    deleted += len(chunk)
                except discord.HTTPException as e:
                    if e.status == 429:
                        await asyncio.sleep(float(getattr(e, "retry_after", 1.5)))
                        try:
                            await channel.delete_messages(chunk)
                            deleted += len(chunk)
                            continue
                        except Exception:
                            skipped += len(chunk)
                    else:
                        skipped += len(chunk)
                await asyncio.sleep(1.1)

            # Old messages: delete one-by-one with a tiny gap.
            for m in single_deletable:
                try:
                    await m.delete()
                    deleted += 1
                except discord.HTTPException:
                    skipped += 1
                await asyncio.sleep(0.6)

            summary = (
                f"Deleted **{format_number(deleted)}** {pluralize(deleted, 'message')} "
                f"in {channel.mention}."
            )
            if skipped:
                summary += f"\nSkipped **{format_number(skipped)}** (couldn't bulk-delete or rate-limited)."

            await btn_interaction.followup.send(
                embed=obsidian_embed(
                    "Filtered Purge Complete",
                    summary,
                    color=discord.Color.green(),
                    footer="Mod only • See also: /mod purge",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
            try:
                from core.audit import log_audit
                await log_audit(
                    interaction.guild.id, "purge_filter", interaction.user.id,
                    details=f"{deleted} matched / {skipped} skipped in #{channel.name}",
                    bot=interaction.client,
                )
            except Exception:
                pass

        view = ConfirmView(on_confirm)
        await interaction.followup.send(embed=preview, view=view, ephemeral=True)
