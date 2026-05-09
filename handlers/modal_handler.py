"""
Modal submission handler.

Extracted from bot.py on_interaction to keep the main bot file navigable.
Entry point: handle_modal_submit(bot, interaction)
"""
from __future__ import annotations
import asyncio
import random
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Any, Optional

from core.config import DB_PATH
from database import now_utc, log_complaint_action
from core.utils import obsidian_embed, is_mod, get_mod_role
from core.channels import resolve_channel_id

logger = logging.getLogger(__name__)

# Deduplication set (in-memory, resets on bot restart)
_processed_modal_submissions: set[str] = set()


async def handle_modal_submit(bot: discord.Client, interaction: discord.Interaction) -> None:
    """Route a modal_submit interaction to the appropriate handler."""
    from views import ComplaintModView
    from core.modals import ComplaintModal
    from core.utils import format_thread_name, dm_blocked_help_embed
    import os as _os
    COMPLAINTS_CHANNEL_ID = int(_os.getenv("COMPLAINTS_CHANNEL_ID", "0") or "0")
    COMPLAINTS_CHANNEL_NAME = _os.getenv("COMPLAINTS_CHANNEL_NAME", "docket-log")
    cid = interaction.data.get("custom_id") if interaction.data else None

    # Log that we received a modal submission
    logger.info(f"[modal] Received modal submission: {cid} (ID: {interaction.id})")

    # Handle RequestInfoModal submissions
    if cid and cid.startswith("request_info_"):
        # Extract case_id from custom_id
        case_id = cid.replace("request_info_", "")

        # Check if interaction is already responded to (by on_submit or another handler)
        # If not done, try to defer (but handle race condition where on_submit defers first)
        if not interaction.response.is_done():
            # Need to defer - on_submit didn't catch it (or we got here first)
            logger.info(f"[modal] RequestInfoModal: Interaction not deferred yet, deferring now")
            try:
                await interaction.response.defer(ephemeral=True)
                logger.info(f"[modal] RequestInfoModal: Deferred interaction successfully")
            except discord.errors.NotFound as defer_err:
                # Interaction expired - can't process it
                logger.warning(f"[modal] RequestInfoModal: Interaction expired (404), cannot process: {defer_err}")
                return
            except (discord.errors.InteractionResponded, discord.errors.HTTPException) as defer_err:
                # Interaction already acknowledged by on_submit or another handler
                logger.info(f"[modal] RequestInfoModal: Could not defer (already acknowledged): {defer_err}")
                # Proceed with processing - interaction was acknowledged
                logger.info(f"[modal] RequestInfoModal: Proceeding with processing despite defer error (interaction was acknowledged)")
        else:
            logger.info(f"[modal] RequestInfoModal: Interaction already done (deferred by on_submit), proceeding with processing")

        try:

            # Extract question from interaction data
            idata_ri: Any = interaction.data or {}
            components = idata_ri.get("components", [])
            question_val = ""

            for component in components:
                components_list = component.get("components", [])
                for comp in components_list:
                    comp_id = comp.get("custom_id", "")
                    value = comp.get("value", "")
                    if comp_id == "question":
                        question_val = value

            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                await interaction.followup.send("Sorry, but you are not an Administrator in this server.", ephemeral=True)
                return

            guild_ri = interaction.guild
            if guild_ri is None:
                await interaction.followup.send("This can only be used in a server.", ephemeral=True)
                return

            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                    (guild_ri.id, case_id),
                )
                row = await cur.fetchone()
            if not row:
                await interaction.followup.send("Case not found.", ephemeral=True)
                return

            user_id = int(row[0])

            # Set status, DM user
            view = ComplaintModView(case_id)
            await view.set_status(interaction, "NEEDS INFO", bot=bot, dm_override=False)

            user = guild_ri.get_member(user_id) or await bot.fetch_user(user_id)
            evidence_dm_ok = False
            if user:
                try:
                    e = obsidian_embed(
                        f"Evidence Requested • {case_id}",
                        f"**Staff request:**\n{question_val}\n\n"
                        "Respond using:\n"
                        f"**/submit_complaint** (case_id: `{case_id}`)\n\n"
                        "_If you don't get this in DMs, enable DMs from this server and ask staff._",
                        color=discord.Color.orange(),
                        client=bot,
                    )
                    await user.send(embed=e)
                    evidence_dm_ok = True
                except discord.Forbidden:
                    pass

            await log_complaint_action(guild_ri, case_id, interaction.user.id, "REQUEST_INFO", question_val)

            if evidence_dm_ok:
                await interaction.followup.send(
                    f"Evidence request logged for `{case_id}`. The reporter was **DM'd** with next steps.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"Evidence request logged for `{case_id}`. **Couldn't DM the reporter** — they may have DMs off. "
                    "Ping them in-channel or ask them to allow DMs from server members.",
                    ephemeral=True,
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"Error requesting evidence: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"Error requesting evidence: {e}", ephemeral=True)
            except Exception:
                pass
        return

    if cid == "complaint_modal":
        # Check if already processed (prevent duplicates)
        # Use interaction ID as unique identifier
        interaction_key = f"{interaction.id}:{interaction.user.id}"

        # Check if already processed
        if interaction_key in _processed_modal_submissions:
            logger.info(f"[modal] Already processed: {interaction_key}")
            return  # Already processed

        # Check if interaction is already responded to (by on_submit or another handler)
        # If not done, try to defer (but handle race condition where on_submit defers first)
        if not interaction.response.is_done():
            # Need to defer - on_submit didn't catch it (or we got here first)
            logger.info(f"[modal] Interaction not deferred yet, deferring now")
            try:
                await interaction.response.defer(ephemeral=True)
                logger.info(f"[modal] Deferred interaction successfully: {interaction_key}")
            except discord.errors.NotFound as defer_err:
                # Interaction expired - can't process it
                logger.warning(f"[modal] Interaction expired (404), cannot process: {defer_err}")
                return
            except (discord.errors.InteractionResponded, discord.errors.HTTPException) as defer_err:
                # Interaction already acknowledged by on_submit or another handler
                # Check if it's done now - if so, proceed with processing
                logger.info(f"[modal] Could not defer (already acknowledged): {defer_err}")
                # Even if is_done() is False, if we got "already acknowledged", 
                # it means someone else acknowledged it, so proceed with processing
                # The interaction will be marked as done when we try to use it
                logger.info(f"[modal] Proceeding with processing despite defer error (interaction was acknowledged)")
            except Exception as defer_err:
                logger.error(f"[modal] Unexpected error during defer: {defer_err}", exc_info=True)
                return
        else:
            logger.info(f"[modal] Interaction already done (deferred by on_submit), proceeding with processing")

        try:

            # Extract values from interaction data
            idata_cm: Any = interaction.data or {}
            components = idata_cm.get("components", [])
            category_val = ""
            details_val = ""
            evidence_val = ""

            for component in components:
                components_list = component.get("components", [])
                for comp in components_list:
                    comp_id = comp.get("custom_id", "")
                    value = comp.get("value", "")
                    if comp_id == "category":
                        category_val = value
                    elif comp_id == "details":
                        details_val = value
                    elif comp_id == "evidence":
                        evidence_val = value

            # Process complaint submission directly
            guild = interaction.guild
            if not guild:
                return await interaction.followup.send("This command can only be used in a server.", ephemeral=True)

            # Check for duplicate BEFORE marking as processed (fixes race condition)
            async with aiosqlite.connect(DB_PATH) as db:
                # Check if this exact submission already exists (same user, same content, within last 5 seconds)
                # Convert ISO 8601 datetime to SQLite datetime format for proper comparison
                # Use datetime(created_at) to convert ISO format to SQLite datetime, then compare
                check_cur = await db.execute(
                    "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND datetime(created_at) > datetime('now', '-5 seconds')",
                    (guild.id, interaction.user.id, category_val, details_val)
                )
                existing = await check_cur.fetchone()
                if existing:
                    # Duplicate detected - don't process
                    logger.info(f"[modal] Duplicate submission detected: {interaction_key}")
                    await interaction.followup.send("This submission was already processed.", ephemeral=True)
                    return

            # Mark as processing AFTER duplicate check passes
            _processed_modal_submissions.add(interaction_key)
            logger.info(f"[modal] Processing complaint submission: {interaction_key}")

            # Generate unique case_id with retry logic
            created = now_utc()
            max_retries = 10
            case_id = None

            for attempt in range(max_retries):
                # Use microseconds for better uniqueness, plus random component
                timestamp_part = int(created.timestamp() * 1000000)  # microseconds
                random_part = random.randint(1000, 9999)
                user_part = interaction.user.id % 10000
                case_id = f"OBS-{timestamp_part}-{user_part}-{random_part}"

                # Check if this case_id already exists
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                        (guild.id, case_id)
                    )
                    exists = await cur.fetchone()

                if not exists:
                    break  # Unique case_id found

                # If we've exhausted retries, use a more unique approach and verify it
                if attempt == max_retries - 1:
                    # Fallback: use full timestamp with nanoseconds simulation
                    import time
                    fallback_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"

                    # Verify fallback ID is unique before using it
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                            (guild.id, fallback_id)
                        )
                        fallback_exists = await cur.fetchone()

                    if not fallback_exists:
                        case_id = fallback_id
                    else:
                        # Last resort: use timestamp + user_id + very large random number
                        # Verify this last resort ID is unique before using it
                        last_resort_id = None
                        for final_attempt in range(5):  # Try up to 5 times for last resort
                            candidate_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                            async with aiosqlite.connect(DB_PATH) as db:
                                cur = await db.execute(
                                    "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                    (guild.id, candidate_id)
                                )
                                exists = await cur.fetchone()
                            if not exists:
                                last_resort_id = candidate_id
                                break
                        # If still no unique ID after 5 attempts, use the candidate anyway (very unlikely collision)
                        case_id = last_resort_id or f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"

            created_iso = created.isoformat()

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        guild.id,
                        case_id,
                        interaction.user.id,
                        created_iso,
                        category_val,
                        details_val,
                        evidence_val,
                        "OPEN",
                        None,
                        created_iso,
                    ),
                )
                await db.commit()

            complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
            ch = guild.get_channel(complaints_id) if complaints_id else None
            if not isinstance(ch, discord.TextChannel):
                return await interaction.followup.send(
                    "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                    ephemeral=True,
                )

            # Type guard: ensure case_id is not None
            if not case_id:
                return await interaction.followup.send("Error: Failed to generate case ID.", ephemeral=True)

            # Type narrowing: ch is now guaranteed to be discord.TextChannel
            assert isinstance(ch, discord.TextChannel)

            mod_role = get_mod_role(guild)
            mention = mod_role.mention if mod_role else "**Administrators**"

            desc = f"**Category:** {category_val}\n\n**Details:**\n{details_val}"
            if evidence_val.strip():
                desc += f"\n\n**Evidence:** {evidence_val}"

            embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red(), client=bot)
            embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

            view = ComplaintModView(case_id)
            msg = await ch.send(content=mention, embed=embed, view=view)  # type: ignore
            bot.add_view(view)

            # Thread for staff discussion (tries private first; falls back)
            thread_id: Optional[int] = None  # type: ignore
            thread_name = format_thread_name(case_id, interaction.user, category_val, created_iso)
            staff_thread: Optional[discord.Thread] = None  # type: ignore
            try:
                staff_thread = await ch.create_thread(  # type: ignore
                    name=thread_name,
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason="Private staff thread for complaint",
                )
                thread_id = staff_thread.id if staff_thread else None
                if mod_role and staff_thread:
                    try:
                        await staff_thread.add_user(interaction.user)  # Might fail; ignore
                    except Exception:
                        pass
            except Exception:
                try:
                    staff_thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                    thread_id = staff_thread.id if staff_thread else None
                except Exception:
                    staff_thread = None

            if thread_id and staff_thread:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                        (thread_id, guild.id, case_id),
                    )
                    await db.commit()
                try:
                    await staff_thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps.", client=bot))
                except Exception:
                    pass

            await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

            await interaction.followup.send(
                embed=obsidian_embed(
                    "Docket Sealed",
                    f"Your docket entry has been sealed as **`{case_id}`**.\nYou'll receive DM docket updates as it progresses.",
                    color=discord.Color.green(),
                    client=bot,
                ),
                ephemeral=True,
            )
            logger.info(f"[modal] Successfully created complaint: {case_id}")
        except Exception as e:
            # Handle errors in modal submission
            logger.error(f"[modal] Error in complaint modal submission: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"Error submitting docket: {str(e)}", ephemeral=True)
                else:
                    try:
                        await interaction.response.send_message(f"Error submitting docket: {str(e)}", ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded) as err:
                        logger.warning(f"[modal] Could not send error response: {err}")
            except Exception as err:
                # If we can't send error message, log it
                logger.error(f"[modal] Could not send error message: {err}", exc_info=True)
        finally:
            # Clean up tracking after a delay (allow time for any duplicate processing to be caught)
            if 'interaction_key' in locals():
                try:
                    await asyncio.sleep(2)
                    _processed_modal_submissions.discard(interaction_key)
                except Exception:
                    pass
        return

    # Handle ApplicationResponseModal submissions
    if cid and cid.startswith("application_response_"):
        # Extract application_id and question_id from custom_id
        # Format: application_response_{application_id}_{question_id}
        parts = cid.replace("application_response_", "").split("_")
        if len(parts) >= 2:
            application_id = int(parts[0])
            question_id = int(parts[1])

            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    pass

            # Extract response from interaction data
            idata_ar: Any = interaction.data or {}
            components = idata_ar.get("components", [])
            response_text = ""

            for component in components:
                components_list = component.get("components", [])
                for comp in components_list:
                    comp_id = comp.get("custom_id", "")
                    value = comp.get("value", "")
                    if comp_id == "response":
                        response_text = value

            if not response_text.strip():
                await interaction.followup.send("Response cannot be empty.", ephemeral=True)
                return

            # Save response
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO application_responses (application_id, question_id, response_text)
                    VALUES (?, ?, ?)
                """, (application_id, question_id, response_text))

                # Update current_question_index
                await db.execute("""
                    UPDATE applications
                    SET current_question_index = current_question_index + 1
                    WHERE id = ?
                """, (application_id,))
                await db.commit()

                # Get guild_id and user_id
                cur = await db.execute("""
                    SELECT guild_id, user_id FROM applications WHERE id = ?
                """, (application_id,))
                row = await cur.fetchone()

            if row:
                guild_id, user_id = row[0], row[1]
                from commands.applications.application import send_next_question
                from core.utils import dm_blocked_help_embed

                ok = await send_next_question(bot, guild_id, user_id, application_id)
                if ok:
                    await interaction.followup.send(
                        embed=obsidian_embed(
                            "Saved",
                            "Your answer is recorded. **Check your DMs** for the next step. _(Only you see this.)_",
                            color=discord.Color.green(),
                            client=bot,
                        ),
                        ephemeral=True,
                    )
                else:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE applications SET current_question_index = current_question_index - 1 WHERE id = ?",
                            (application_id,),
                        )
                        await db.execute(
                            "DELETE FROM application_responses WHERE application_id = ? AND question_id = ?",
                            (application_id, question_id),
                        )
                        await db.commit()
                    await interaction.followup.send(
                        embed=dm_blocked_help_embed(
                            "Couldn't send the next question",
                            "Your last answer wasn't saved because I need **Direct Messages** open to continue. "
                            "Enable DMs from this server, then submit your answer again from the same question in your DMs.",
                            client=bot,
                        ),
                        ephemeral=True,
                    )
            else:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "Couldn't find that application",
                        "It may have been cancelled or already submitted. Start again from the application channel if you still need to apply.",
                        color=discord.Color.orange(),
                        client=bot,
                    ),
                    ephemeral=True,
                )
        return

    # Handle ApplicationQuestionModal submissions
    if cid and cid.startswith("application_question_"):
        # This is handled in the modal's on_submit, but we can add logging here if needed
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                pass
        return

    # Handle ApplicationRejectModal submissions
    if cid and cid.startswith("application_reject_"):
        # This is handled in the modal's on_submit
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                pass
        return

    # For other modals (with auto-generated custom_ids from previous bot sessions),
    # try to extract data from the interaction and process it as a complaint
    # This handles cases where the modal was created before the bot restarted
    logger.info(f"[modal] Unknown modal custom_id: {cid} - attempting to extract as complaint modal")

    # Extract modal data - helper function to get values from any modal submission
    def extract_modal_values(interaction_data):
        """Extract text input values from modal interaction data"""
        values = {}
        components = interaction_data.get("components", [])
        for row in components:
            if "components" in row:
                for component in row["components"]:
                    comp_id = component.get("custom_id", "")
                    comp_value = component.get("value", "")
                    if comp_id:
                        values[comp_id] = comp_value
        return values

    # Try to extract complaint data from the modal submission
    try:
        values = extract_modal_values(interaction.data or {})

        # Check if this looks like a complaint modal (has category, details fields)
        if "category" in values or "details" in values:
            # This is likely a complaint modal submission - process it
            logger.info(f"[modal] Detected complaint modal from auto-generated ID, extracting values: {list(values.keys())}")

            # Process it the same way as complaint_modal (reuse existing handler logic)
            # Import the processing function or inline it here
            interaction_key = f"{interaction.id}:{interaction.user.id}"
            if interaction_key in _processed_modal_submissions:
                logger.info(f"[modal] Already processed: {interaction_key}")
                return

            _processed_modal_submissions.add(interaction_key)

            try:
                # Defer if not already done
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)

                # Extract values
                category_val = values.get("category", "")
                details_val = values.get("details", "")
                evidence_val = values.get("evidence", "")

                # Process complaint using same logic as complaint_modal handler
                # This is duplicated but necessary for persistence after bot restarts
                guild = interaction.guild
                if not guild:
                    return await interaction.followup.send("This command can only be used in a server.", ephemeral=True)

                # Generate unique case_id with retry logic
                created = now_utc()
                max_retries = 10
                case_id = None

                for attempt in range(max_retries):
                    timestamp_part = int(created.timestamp() * 1000000)
                    random_part = random.randint(1000, 9999)
                    user_part = interaction.user.id % 10000
                    case_id = f"OBS-{timestamp_part}-{user_part}-{random_part}"

                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                            (guild.id, case_id)
                        )
                        exists = await cur.fetchone()

                    if not exists:
                        break

                    if attempt == max_retries - 1:
                        # Fallback: use full timestamp with nanoseconds simulation
                        import time
                        fallback_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(10000, 99999)}"

                        # Verify fallback ID is unique before using it
                        async with aiosqlite.connect(DB_PATH) as db:
                            cur = await db.execute(
                                "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                (guild.id, fallback_id)
                            )
                            fallback_exists = await cur.fetchone()

                        if not fallback_exists:
                            case_id = fallback_id
                        else:
                            # Last resort: use timestamp + user_id + very large random number
                            # Verify this last resort ID is unique before using it
                            last_resort_id = None
                            for final_attempt in range(5):  # Try up to 5 times for last resort
                                candidate_id = f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"
                                async with aiosqlite.connect(DB_PATH) as db:
                                    cur = await db.execute(
                                        "SELECT 1 FROM complaints WHERE guild_id=? AND case_id=?",
                                        (guild.id, candidate_id)
                                    )
                                    exists = await cur.fetchone()
                                if not exists:
                                    last_resort_id = candidate_id
                                    break
                            # If still no unique ID after 5 attempts, use the candidate anyway (very unlikely collision)
                            case_id = last_resort_id or f"OBS-{int(time.time() * 1000000)}-{interaction.user.id}-{random.randint(100000, 999999)}"

                created_iso = created.isoformat()

                # Check for duplicates
                async with aiosqlite.connect(DB_PATH) as db:
                    # Convert ISO 8601 datetime to SQLite datetime format for proper comparison
                    check_cur = await db.execute(
                        "SELECT case_id FROM complaints WHERE guild_id=? AND user_id=? AND category=? AND details=? AND datetime(created_at) > datetime('now', '-5 seconds')",
                        (guild.id, interaction.user.id, category_val, details_val)
                    )
                    existing = await check_cur.fetchone()
                    if existing:
                        _processed_modal_submissions.discard(interaction_key)
                        await interaction.followup.send("This submission was already processed.", ephemeral=True)
                        return

                    await db.execute(
                        "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (guild.id, case_id, interaction.user.id, created_iso, category_val, details_val, evidence_val, "OPEN", None, created_iso),
                    )
                    await db.commit()

                complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
                ch = guild.get_channel(complaints_id) if complaints_id else None
                if not isinstance(ch, discord.TextChannel):
                    return await interaction.followup.send(
                        "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                        ephemeral=True,
                    )

                # Type guard: ensure case_id is not None
                if not case_id:
                    return await interaction.followup.send("Error: Failed to generate case ID.", ephemeral=True)

                # Type narrowing: ch is now guaranteed to be discord.TextChannel
                assert isinstance(ch, discord.TextChannel)

                mod_role = get_mod_role(guild)
                mention = mod_role.mention if mod_role else "**Administrators**"

                desc = f"**Category:** {category_val}\n\n**Details:**\n{details_val}"
                if evidence_val.strip():
                    desc += f"\n\n**Evidence:** {evidence_val}"

                embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red(), client=bot)
                embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")

                view = ComplaintModView(case_id)
                msg = await ch.send(content=mention, embed=embed, view=view)  # type: ignore
                bot.add_view(view)

                # Create staff thread
                thread_id: Optional[int] = None  # type: ignore
                thread_name = format_thread_name(case_id, interaction.user, category_val, created_iso)
                staff_thread: Optional[discord.Thread] = None  # type: ignore
                try:
                    staff_thread = await ch.create_thread(  # type: ignore
                        name=thread_name,
                        type=discord.ChannelType.private_thread,
                        invitable=False,
                        reason="Private staff thread for complaint",
                    )
                    thread_id = staff_thread.id if staff_thread else None
                    if mod_role and staff_thread:
                        try:
                            await staff_thread.add_user(interaction.user)
                        except Exception:
                            pass
                except Exception:
                    try:
                        staff_thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
                        thread_id = staff_thread.id if staff_thread else None
                    except Exception:
                        staff_thread = None

                if thread_id and staff_thread:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                            (thread_id, guild.id, case_id),
                        )
                        await db.commit()
                    try:
                        await staff_thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps.", client=bot))
                    except Exception:
                        pass

                await log_complaint_action(guild, case_id, interaction.user.id, "FILED")

                await interaction.followup.send(
                    embed=obsidian_embed(
                        "Docket Sealed",
                        f"Your docket entry has been sealed as **`{case_id}`**.\nYou'll receive DM docket updates as it progresses.",
                        color=discord.Color.green(),
                        client=bot,
                    ),
                    ephemeral=True,
                )
                logger.info(f"[modal] Successfully created complaint from auto-generated modal: {case_id}")

            except Exception as e:
                logger.error(f"[modal] Error processing auto-generated modal: {e}", exc_info=True)
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send("Error processing docket submission.", ephemeral=True)
                    else:
                        await interaction.response.send_message("Error processing docket submission.", ephemeral=True)
                except Exception:
                    pass
            finally:
                try:
                    await asyncio.sleep(2)
                    _processed_modal_submissions.discard(interaction_key)
                except Exception:
                    pass
            return

    except Exception as e:
        logger.error(f"[modal] Error extracting data from unknown modal: {e}", exc_info=True)

    # If we can't handle it, defer and send a generic error message instead of letting discord.py handle it
    # (which would cause the "process_application_commands" error)
    logger.warning(f"[modal] Could not handle modal with custom_id: {cid} - sending generic error")
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("This modal is no longer valid. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("This modal is no longer valid. Please try again.", ephemeral=True)
    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
        # Interaction expired or already handled - can't send error message
        logger.warning(f"[modal] Could not send error message for unknown modal: {cid}")
    return
