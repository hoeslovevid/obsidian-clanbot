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

from core.config import DB_PATH
from core.utils import is_mod, obsidian_embed
from core.reply_helpers import deny_mods_only, reply_error
from core.vc_permissions import (
    apply_staff_overwrites_to_mapping,
    can_manage_temp_vc,
    get_vc_staff_roles,
)

logger = logging.getLogger(__name__)


async def handle_component(bot: discord.Client, interaction: discord.Interaction) -> None:
    """Route a component interaction (button / select menu) to the appropriate handler."""
    from views import ComplaintModView, RSVPView, SetLimitView
    from core.modals import ComplaintModal, RenameVCModal, InviteModal, RemoveAccessModal, TransferOwnerModal
    from core.channels import delete_temp_vc_and_panel
    try:
        cid = interaction.data.get("custom_id") if interaction.data else None
        if not cid:
            return

        # discord.py dispatches bot.add_view() callbacks before on_interaction.
        # Skip duplicate handling (InteractionResponded / error 40060).
        if interaction.response.is_done():
            return

        if cid.startswith("obsidian_console:"):
            from core.console_hub import respond_console_hub_hint

            action = cid.split(":", 1)[1]
            if await respond_console_hub_hint(interaction, action):
                return

        if cid == "world_state:refresh":
            from commands.warframe.world_state import refresh_pinned_world_state

            await refresh_pinned_world_state(bot, interaction)
            return

        if cid == "obsidian:refresh":
            from core.refresh_panels import handle_refresh_button

            try:
                await handle_refresh_button(bot, interaction)
            except (discord.InteractionResponded, discord.HTTPException) as exc:
                if getattr(exc, "code", None) != 40060 and not isinstance(
                    exc, discord.InteractionResponded
                ):
                    raise
            return

        if cid == "obsidian:wf_retry":
            from core.wf_retry_panels import handle_wf_retry_button

            try:
                await handle_wf_retry_button(bot, interaction)
            except (discord.InteractionResponded, discord.HTTPException) as exc:
                if getattr(exc, "code", None) != 40060 and not isinstance(
                    exc, discord.InteractionResponded
                ):
                    raise
            return

        if cid.startswith("wf_hub:"):
            from core.wf_hub_actions import handle_wf_hub_button

            if await handle_wf_hub_button(interaction, cid):
                return

        if cid.startswith("panel:"):
            from core.action_panel_views import handle_panel_action

            if await handle_panel_action(interaction, cid):
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
                        await reply_error(
                            interaction,
                            "Couldn't open form",
                            "Failed to open docket form. Please try again.",
                        )
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
                    return await deny_mods_only(interaction)

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

                if action == "ticket":
                    try:
                        await interaction.response.defer(ephemeral=True)
                    except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                        return
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT user_id, category FROM complaints WHERE guild_id=? AND case_id=?",
                            (interaction.guild.id, case_id),
                        )
                        row = await cur.fetchone()
                    if not row:
                        return await interaction.followup.send("Case not found.", ephemeral=True)
                    reporter_id, category = int(row[0]), row[1] or "complaint"
                    from commands.tickets.ticket import open_support_ticket
                    await open_support_ticket(
                        interaction,
                        f"[{case_id}] {category}",
                        tag_val="complaint-escalation",
                        priority_val="urgent",
                        channel_preamble=(
                            f"Escalated from complaint **{case_id}** — reporter <@{reporter_id}>."
                        ),
                    )
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

        if cid.startswith("events:delay:"):
            try:
                minutes = int(cid.split(":")[-1])
            except ValueError:
                minutes = 15
            view = RSVPView()
            await view.delay_event(interaction, minutes)
            return

        if cid == "events:cancel":
            view = RSVPView()
            await view.cancel_event(interaction)
            return

        # Voice: VC panel actions: vc:{vc_id}:{action}
        if cid.startswith("vc:"):
            parts = cid.split(":")
            if len(parts) >= 3:
                vc_id_s, action = parts[1], parts[2]
                try:
                    vc_id = int(vc_id_s)
                except ValueError:
                    return await reply_error(interaction, "Invalid reference", "Invalid channel reference.")

                # Permission check (owner or mods)
                member = interaction.user
                if not isinstance(member, discord.Member):
                    return await reply_error(interaction, "Not allowed", "This action isn't available here.")

                guild_vc = interaction.guild
                if guild_vc is None:
                    return await reply_error(interaction, "Not allowed", "This action isn't available here.")

                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                        (guild_vc.id, vc_id),
                    )
                    row = await cur.fetchone()
                owner_id = int(row[0]) if row else None

                if not await can_manage_temp_vc(member, guild_vc, owner_id=owner_id):
                    return await interaction.response.send_message(
                        "Only the squad owner or staff (configured mod roles) may do that.",
                        ephemeral=True,
                    )

                vc = guild_vc.get_channel(vc_id)
                if not isinstance(vc, discord.VoiceChannel):
                    return await reply_error(interaction, "Not found", "Channel not found.")

                # Helpers for @everyone overwrite tweaks
                async def edit_everyone(*, connect: Optional[bool] = None, view: Optional[bool] = None):
                    overwrites = dict(vc.overwrites)
                    base = overwrites.get(guild_vc.default_role, discord.PermissionOverwrite())
                    if connect is not None:
                        base.connect = connect
                    if view is not None:
                        base.view_channel = view
                    overwrites[guild_vc.default_role] = base

                    staff_roles = await get_vc_staff_roles(guild_vc)
                    overwrites = apply_staff_overwrites_to_mapping(overwrites, staff_roles)

                    # Owner stays able to view/connect
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (guild_vc.id, vc.id),
                        )
                        row = await cur.fetchone()
                    owner_id = int(row[0]) if row else member.id
                    owner = guild_vc.get_member(owner_id)
                    if owner:
                        owner_ow = overwrites.get(owner, discord.PermissionOverwrite())
                        owner_ow.view_channel = True
                        owner_ow.connect = True
                        overwrites[owner] = owner_ow

                    await vc.edit(overwrites=overwrites, reason="VC panel action")

                if action == "rename":
                    await interaction.response.send_modal(RenameVCModal(vc_id))
                    return

                if action == "limit":
                    await interaction.response.send_message("Choose a squad limit:", view=SetLimitView(vc_id), ephemeral=True)
                    return

                if action.startswith("cap_"):
                    try:
                        limit = int(action.split("_", 1)[1])
                    except (IndexError, ValueError):
                        return await interaction.response.send_message("Invalid capacity preset.", ephemeral=True)
                    await vc.edit(user_limit=limit, reason="VC panel capacity preset")
                    label = "Capacity removed — **no limit**." if limit == 0 else f"Capacity set to **{limit}**."
                    await interaction.response.send_message(label, ephemeral=True)
                    from bot import update_vc_panel_embed
                    await update_vc_panel_embed(guild_vc, vc_id, force=True)
                    return

                if action == "lock":
                    await edit_everyone(connect=False)
                    await interaction.response.send_message("Sealed.", ephemeral=True)
                    from bot import update_vc_panel_embed
                    await update_vc_panel_embed(guild_vc, vc_id, force=True)
                    return

                if action == "unlock":
                    await edit_everyone(connect=True)
                    await interaction.response.send_message("Unsealed.", ephemeral=True)
                    from bot import update_vc_panel_embed
                    await update_vc_panel_embed(guild_vc, vc_id, force=True)
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

                if action in ("privacy_public", "privacy_friends", "privacy_private"):
                    mode = action.replace("privacy_", "")
                    owner_id = member.id
                    async with aiosqlite.connect(DB_PATH) as db:
                        cur = await db.execute(
                            "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                            (guild_vc.id, vc_id),
                        )
                        row = await cur.fetchone()
                        if row:
                            owner_id = int(row[0])
                    owner = guild_vc.get_member(owner_id) or member
                    overwrites = dict(vc.overwrites)
                    if mode == "public":
                        overwrites[guild_vc.default_role] = discord.PermissionOverwrite(
                            view_channel=True, connect=True
                        )
                    elif mode == "friends":
                        overwrites[guild_vc.default_role] = discord.PermissionOverwrite(
                            view_channel=True, connect=False
                        )
                        for occupant in vc.members:
                            if occupant.bot:
                                continue
                            ow = overwrites.get(occupant, discord.PermissionOverwrite())
                            ow.view_channel = True
                            ow.connect = True
                            overwrites[occupant] = ow
                    else:  # private
                        overwrites[guild_vc.default_role] = discord.PermissionOverwrite(
                            view_channel=False, connect=False
                        )
                    owner_ow = overwrites.get(owner, discord.PermissionOverwrite())
                    owner_ow.view_channel = True
                    owner_ow.connect = True
                    owner_ow.manage_channels = True
                    owner_ow.move_members = True
                    overwrites[owner] = owner_ow
                    staff_roles = await get_vc_staff_roles(guild_vc)
                    overwrites = apply_staff_overwrites_to_mapping(overwrites, staff_roles)
                    await vc.edit(overwrites=overwrites, reason=f"VC privacy preset: {mode}")
                    labels = {
                        "public": "🌐 **Public** — anyone can see and join.",
                        "friends": "👥 **Friends** — squad in the channel can stay; others need **Grant**.",
                        "private": "🔐 **Private** — hidden from everyone except you and mods.",
                    }
                    await interaction.response.send_message(labels.get(mode, "Privacy updated."), ephemeral=True)
                    return

        # LFG: DM mark-as-filled button (works from DMs where guild is None)
        if cid.startswith("lfg:"):
            parts = cid.split(":")
            if len(parts) >= 3 and parts[2] == "squad_vc":
                try:
                    lfg_id = int(parts[1])
                except ValueError:
                    return await reply_error(interaction, "Invalid LFG", "Invalid LFG reference.")
                if not interaction.guild or not isinstance(interaction.user, discord.Member):
                    from core.reply_helpers import deny_server_only
                    return await deny_server_only(interaction)
                await interaction.response.defer(ephemeral=True)
                from core.lfg_squad_vc import create_squad_vc_for_lfg

                _ok, msg, _vc = await create_squad_vc_for_lfg(
                    bot, interaction.guild, lfg_id, interaction.user,
                )
                await interaction.followup.send(msg, ephemeral=True)
                return
            if len(parts) >= 3 and parts[2] == "dm_fill":
                try:
                    lfg_id = int(parts[1])
                except ValueError:
                    return await reply_error(interaction, "Invalid LFG", "Invalid LFG reference.")
                from core.lfg_fill import mark_lfg_filled

                await interaction.response.defer(ephemeral=True)
                ok, msg = await mark_lfg_filled(
                    lfg_id,
                    interaction.user.id,
                    client=interaction.client,
                    guild=interaction.guild,
                )
                if ok:
                    try:
                        from core.lfg_fill import LFGDMMarkFilledView
                        view = LFGDMMarkFilledView(lfg_id)
                        for child in view.children:
                            if isinstance(child, discord.ui.Button):
                                child.disabled = True
                        await interaction.edit_original_response(view=view)
                    except Exception:
                        pass
                await interaction.followup.send(msg, ephemeral=True)
                return
            if len(parts) >= 3 and parts[2] == "repost":
                try:
                    lfg_id = int(parts[1])
                except ValueError:
                    return await reply_error(interaction, "Invalid LFG", "Invalid LFG reference.")
                from core.lfg_repost import open_lfg_repost_modal

                await open_lfg_repost_modal(interaction, bot, lfg_id)
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

        from core.interaction_recovery import is_expired_interaction, reply_expired_panel

        if is_expired_interaction(e):
            cid = interaction.data.get("custom_id") if interaction.data else None
            await reply_expired_panel(interaction, custom_id=cid)
            return

        # Send a consistent, user-friendly error embed (with error code + copy
        # button) instead of leaking the raw exception string. send_error_reply
        # handles response-vs-followup and swallows expired-interaction errors.
        try:
            from core.error_handling import (
                classify_exception,
                record_error,
                send_error_reply,
            )

            user_message, action_hint, error_code = classify_exception(e)
            record_error(
                error_code=error_code,
                command_name=cid,
                guild_id=interaction.guild.id if interaction.guild else None,
                exc=e,
                user_message=user_message,
            )
            await send_error_reply(
                interaction,
                user_message,
                action_hint=action_hint,
                error_code=error_code,
            )
        except Exception as err:
            # If we can't send error message, log it
            logger.error(f"[outer_handler] Could not send error message: {err}", exc_info=True)
