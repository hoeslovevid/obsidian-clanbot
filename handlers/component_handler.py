"""
Component (button / select) interaction handler.

Extracted from bot.py on_interaction to keep the main bot file navigable.
Entry point: handle_component(bot, interaction)
"""
from __future__ import annotations
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Any, Optional

from config import DB_PATH
from utils import is_mod, obsidian_embed, get_mod_role

logger = logging.getLogger(__name__)


async def handle_component(bot: discord.Client, interaction: discord.Interaction) -> None:
    """Route a component interaction (button / select menu) to the appropriate handler."""
    from views import ComplaintModView, RSVPView, SetLimitView
    from modals import ComplaintModal, RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal
    from channels import delete_temp_vc_and_panel
    try:
        cid = interaction.data.get("custom_id") if interaction.data else None
        if not cid:
            return

        # Complaints: open modal
        if cid == "complaints:open":
            # Check if interaction is still valid (not expired)
            if interaction.response.is_done():
                logger.warning(f"[button] complaints:open - interaction already done")
                return
            try:
                modal = ComplaintModal()
                await interaction.response.send_modal(modal)
                logger.info(f"[button] Sent ComplaintModal with custom_id: {modal.custom_id}")
                return
            except (discord.errors.NotFound, discord.errors.InteractionResponded) as e:
                logger.error(f"[button] complaints:open - interaction expired/already handled: {e}")
                return
            except Exception as e:
                logger.error(f"[button] complaints:open - error sending modal: {e}", exc_info=True)
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message("Failed to open docket form. Please try again.", ephemeral=True)
                except Exception:
                    pass
                return

        # Complaints: mod actions
        if cid.startswith("complaints:"):
            # complaints:{case_id}:{action}
            parts = cid.split(":")
            if len(parts) == 3:
                _, case_id, action = parts
                if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                    return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)

                view = ComplaintModView(case_id)

                # Check if interaction has already been responded to
                if interaction.response.is_done():
                    logger.warning(f"[button] complaints action already handled: {case_id}:{action}")
                    return

                if action == "ack":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:ack - interaction expired/already handled: {e}")
                        return
                    # Use followup for set_status and message (don't call response methods after defer)
                    _, dm_ok = await view.set_status(interaction, "ACKNOWLEDGED", bot=bot)
                    msg = f"`{case_id}` marked reviewed."
                    if not dm_ok:
                        msg += " **Couldn't DM the reporter** — DMs may be off; follow up in-channel if they need a ping."
                    await interaction.followup.send(msg, ephemeral=True)
                    return

                if action == "resolve":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:resolve - interaction expired/already handled: {e}")
                        return
                    _, dm_ok = await view.set_status(interaction, "RESOLVED", bot=bot)
                    msg = f"`{case_id}` closed."
                    if not dm_ok:
                        msg += " **Couldn't DM the reporter** — they may have DMs disabled."
                    await interaction.followup.send(msg, ephemeral=True)
                    return

                if action == "reject":
                    # Defer first to prevent timeout
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                        # Interaction expired or already handled - can't process it
                        logger.warning(f"[button] complaints:reject - interaction expired/already handled: {e}")
                        return
                    _, dm_ok = await view.set_status(interaction, "REJECTED", bot=bot)
                    msg = f"`{case_id}` dismissed."
                    if not dm_ok:
                        msg += " **Couldn't DM the reporter** — they may have DMs disabled."
                    await interaction.followup.send(msg, ephemeral=True)
                    return

                if action == "needinfo":
                    # Check if interaction is still valid
                    if interaction.response.is_done():
                        logger.warning(f"[button] Request Evidence - interaction already done: {case_id}")
                        return
                    try:
                        modal = RequestInfoModal(case_id)
                        await interaction.response.send_modal(modal)
                        logger.info(f"[button] Sent RequestInfoModal for case: {case_id}")
                        return
                    except (discord.errors.NotFound, discord.errors.InteractionResponded) as e:
                        logger.warning(f"[button] Request Evidence - interaction expired/already handled: {case_id}: {e}")
                        # Interaction expired - try to send error via followup if possible
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("The interaction expired. Please try clicking the button again.", ephemeral=True)
                        except Exception:
                            pass
                        return
                    except Exception as e:
                        logger.error(f"[button] Request Evidence - error sending modal: {case_id}: {e}", exc_info=True)
                        try:
                            if interaction.response.is_done():
                                await interaction.followup.send("Failed to open evidence request form. Please try again.", ephemeral=True)
                            else:
                                await interaction.response.send_message("Failed to open evidence request form. Please try again.", ephemeral=True)
                        except Exception:
                            pass
                        return

        # Giveaways: Enter/Leave are handled by the persistent GiveawayView (registered in on_ready).
        # Do not handle giveaway: here or we double-respond and view.enter_giveaway is the Button, not callable.

        # Events: RSVP
        if cid.startswith("events:rsvp:"):
            rsvp_action = cid.split(":")[-1]
            view = RSVPView()
            if rsvp_action == "going":
                await view._set_rsvp(interaction, "GOING")
                return
            if rsvp_action == "maybe":
                await view._set_rsvp(interaction, "MAYBE")
                return
            if rsvp_action == "no":
                await view._set_rsvp(interaction, "NO")
                return

        # Voice: VC panel actions: vc:{vc_id}:{action}
        if cid.startswith("vc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                vc_id_s, action = parts[1], parts[2]
                try:
                    vc_id = int(vc_id_s)
                except ValueError:
                    return await interaction.response.send_message("Invalid channel reference.", ephemeral=True)

                # Permission check (owner or mods)
                member = interaction.user
                if not isinstance(member, discord.Member):
                    return await interaction.response.send_message("Not allowed.", ephemeral=True)

                guild_vc = interaction.guild
                if guild_vc is None:
                    return await interaction.response.send_message("Not allowed.", ephemeral=True)

                allowed = is_mod(member)
                if not allowed:
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (guild_vc.id, vc_id),
                        )
                        row = await cur.fetchone()
                    allowed = bool(row and int(row[0]) == member.id)

                if not allowed:
                    return await interaction.response.send_message("Only the squad owner (or an Administrator) may do that.", ephemeral=True)

                vc = guild_vc.get_channel(vc_id)
                if not isinstance(vc, discord.VoiceChannel):
                    return await interaction.response.send_message("Channel not found.", ephemeral=True)

                # Helpers for @everyone overwrite tweaks
                async def edit_everyone(*, connect: Optional[bool] = None, view: Optional[bool] = None):
                    overwrites = vc.overwrites
                    base = overwrites.get(guild_vc.default_role, discord.PermissionOverwrite())
                    if connect is not None:
                        base.connect = connect
                    if view is not None:
                        base.view_channel = view
                    overwrites[guild_vc.default_role] = base

                    mod_role = get_mod_role(guild_vc)
                    if mod_role:
                        m = overwrites.get(mod_role, discord.PermissionOverwrite())
                        m.view_channel = True
                        m.connect = True
                        overwrites[mod_role] = m

                    # Owner stays able to view/connect
                    owner_ow = overwrites.get(member, discord.PermissionOverwrite())
                    owner_ow.view_channel = True
                    owner_ow.connect = True
                    overwrites[member] = owner_ow

                    await vc.edit(overwrites=overwrites, reason="VC panel action")

                if action == "rename":
                    await interaction.response.send_modal(RenameVCModal(vc_id))
                    return

                if action == "limit":
                    await interaction.response.send_message("Choose a squad limit:", view=SetLimitView(vc_id), ephemeral=True)
                    return

                if action == "lock":
                    await edit_everyone(connect=False)
                    await interaction.response.send_message("Sealed.", ephemeral=True)
                    return

                if action == "unlock":
                    await edit_everyone(connect=True)
                    await interaction.response.send_message("Unsealed.", ephemeral=True)
                    return

                if action == "hide":
                    await edit_everyone(view=False)
                    await interaction.response.send_message("Cloaked.", ephemeral=True)
                    return

                if action == "show":
                    await edit_everyone(view=True)
                    await interaction.response.send_message("Revealed.", ephemeral=True)
                    return

                if action == "invite":
                    await interaction.response.send_modal(InviteModal(vc_id))
                    return

                if action == "remove":
                    await interaction.response.send_modal(RemoveAccessModal(vc_id))
                    return

                if action == "transfer":
                    await interaction.response.send_modal(TransferOwnerModal(vc_id))
                    return

                if action == "disband":
                    await interaction.response.send_message("Cell dissolved.", ephemeral=True)
                    await delete_temp_vc_and_panel(guild_vc, vc_id, reason="Disband via panel")
                    return

        # Trading posts (trade:{id}:sold|delete): handled by TradingPostView callbacks.
        # Those buttons defer and update the message; do not route here — discord.py invokes the
        # persistent view first, and a second defer in this handler caused 40060 already acknowledged.

        # Application panel: start application
        # Note: This is handled by ApplicationPanelView.start_application callback
        # The view callback is called automatically by discord.py when the button is clicked
        # We don't need to handle it here to avoid duplicate processing
        # If the view callback doesn't exist (e.g., after bot restart), the button won't work anyway
        # So we skip handling it here to avoid double-defer errors

        # Applications: approve or reject
        # Note: This is handled by ApplicationManageView callbacks (approve_button, reject_button)
        # The views are registered with bot.add_view() in on_ready, so discord.py will automatically
        # call the view callbacks when buttons are clicked. We don't need to handle it here.
        # The view callbacks handle their own interaction acknowledgment (defer for approve, send_modal for reject).

    except Exception as e:
        # Last-resort error handler - only for component/modal interactions
        # Do NOT handle errors for application commands - let discord.py handle them
        if interaction.type == discord.InteractionType.application_command:
            # Already handled (command usage tracking), just return silently
            # discord.py will handle any actual command errors
            return

        # Also skip if this is a modal submission - it has its own error handler
        if interaction.type == discord.InteractionType.modal_submit:
            # Don't handle here - modal submission has its own handler
            # Filter out process_application_commands errors (they're not real errors)
            if "process_application_commands" in str(e):
                logger.warning(f"[outer_handler] Ignoring process_application_commands error in modal submission (likely stale/cached): {e}")
                return  # Don't send error message to user
            # But log other errors for debugging
            import traceback
            import sys
            error_msg = f"[outer_handler] Modal submission error (should be handled by modal handler): {e}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr, flush=True)
            print(error_msg, flush=True)
            return

        # For component interactions, handle the error
        import traceback
        import sys
        error_traceback = traceback.format_exc()
        error_msg = f"[outer_handler] Component interaction error: {e}\n{error_traceback}"
        logger.error(error_msg)
        print(error_msg, file=sys.stderr, flush=True)
        print(error_msg, flush=True)

        # Don't send error messages about process_application_commands - it's not a real error
        # This error message appears to be cached or from an old code path
        if "process_application_commands" in str(e):
            logger.warning(f"[outer_handler] Ignoring process_application_commands error (likely cached/stale): {e}")
            return  # Don't send error message to user

        # Don't send error messages for expired interactions (404) - we can't respond to them
        if isinstance(e, discord.errors.NotFound) and "Unknown interaction" in str(e):
            logger.warning(f"[outer_handler] Interaction expired (404), cannot send error message: {e}")
            return  # Interaction expired, can't respond

        # Only try to send error message if interaction is still valid
        try:
            if interaction.response.is_done():
                # Try followup, but it might also fail if interaction expired
                try:
                    await interaction.followup.send(f"Something went wrong: {str(e)}", ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    # Interaction expired or already handled - can't send error
                    logger.warning(f"[outer_handler] Could not send error via followup (interaction expired/handled)")
            else:
                try:
                    await interaction.response.send_message(f"Something went wrong: {str(e)}", ephemeral=True)
                except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                    # Interaction already expired or handled
                    logger.warning(f"[outer_handler] Could not send error via response (interaction expired/handled)")
        except Exception as err:
            # If we can't send error message, log it
            logger.error(f"[outer_handler] Could not send error message: {err}", exc_info=True)
