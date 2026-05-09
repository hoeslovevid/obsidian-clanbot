"""
Modal classes for Discord interactions.
This module contains all Modal classes used by the bot.
"""
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Optional

from core.utils import extract_id, get_mod_role, is_mod, obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


# --- Context menu modals (Transfer, Warn, Give Rep) ---

class TransferCoinsModal(discord.ui.Modal, title="Transfer Coins"):
    amount = discord.ui.TextInput(label="Amount", placeholder="e.g. 100", max_length=12)

    def __init__(self, member: discord.Member):
        super().__init__(timeout=300)
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.strip())
        except ValueError:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Amount", "Please enter a valid number.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Amount", "Amount must be greater than 0.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        from commands.economy.transfer import run_transfer_with_modal
        await run_transfer_with_modal(interaction, self.target_member, amount)


class WarnUserModal(discord.ui.Modal, title="Warn User"):
    reason = discord.ui.TextInput(label="Reason", placeholder="Reason for the warning", max_length=500)

    def __init__(self, member: discord.Member):
        super().__init__(timeout=300)
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        from commands.moderation.warn import execute_warn
        from views import ConfirmView

        reason = self.reason.value or "No reason provided"
        embed = obsidian_embed(
            "⚠️ Confirm Warn",
            f"Warn **{self.target_member.display_name}** for:\n\n_{reason}_\n\nThis will be recorded on their profile.",
            color=discord.Color.orange(),
            client=interaction.client,
        )

        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.followup.send("Only the person who started this can confirm.", ephemeral=True)
            if not confirmed:
                return await btn_interaction.followup.send("Warn cancelled.", ephemeral=True)
            await execute_warn(btn_interaction, self.target_member, reason)

        view = ConfirmView(on_confirm)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class GiveRepModal(discord.ui.Modal, title="Give Reputation"):
    reason = discord.ui.TextInput(label="Reason (optional)", placeholder="Why are you giving rep?", required=False, max_length=200)

    def __init__(self, member: discord.Member):
        super().__init__(timeout=300)
        self.target_member = member

    async def on_submit(self, interaction: discord.Interaction):
        from commands.general.reputation import execute_give_rep
        await execute_give_rep(interaction, self.target_member, self.reason.value or None)


class RenameVCModal(discord.ui.Modal, title="Recalibrate Comms Node"):  # type: ignore
    new_name = discord.ui.TextInput(label="New designation", max_length=80)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        await vc.edit(name=str(self.new_name), reason="VC rename")
        await interaction.response.send_message("Renamed.", ephemeral=True)


class InviteModal(discord.ui.Modal, title="Grant Access"):  # type: ignore
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn't read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        ow = overwrites.get(member, discord.PermissionOverwrite())
        ow.view_channel = True
        ow.connect = True
        overwrites[member] = ow
        await vc.edit(overwrites=overwrites, reason="VC invite")
        await interaction.response.send_message(f"Invited {member.mention}.", ephemeral=True)


class RemoveAccessModal(discord.ui.Modal, title="Revoke Access"):  # type: ignore
    target = discord.ui.TextInput(label="User (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        uid = extract_id(str(self.target))
        if not uid:
            return await interaction.response.send_message("Couldn't read that user. Use @mention or ID.", ephemeral=True)

        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        overwrites = vc.overwrites
        if member in overwrites:
            del overwrites[member]
            await vc.edit(overwrites=overwrites, reason="VC remove access")
        await interaction.response.send_message(f"Access removed for {member.mention}.", ephemeral=True)


class TransferOwnerModal(discord.ui.Modal, title="Pass Command"):  # type: ignore
    target = discord.ui.TextInput(label="New owner (@mention or ID)", max_length=60)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)

        new_owner_id = extract_id(str(self.target))
        if not new_owner_id:
            return await interaction.response.send_message("Couldn't read that user. Use @mention or ID.", ephemeral=True)

        new_owner = interaction.guild.get_member(new_owner_id)
        if not new_owner:
            return await interaction.response.send_message("User not in server.", ephemeral=True)

        # Only current owner or mods can transfer
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?", (interaction.guild.id, vc.id))
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Owner record missing.", ephemeral=True)

        current_owner_id = int(row[0])
        actor = interaction.user
        if not isinstance(actor, discord.Member):
            return await interaction.response.send_message("Not allowed.", ephemeral=True)
        if not (is_mod(actor) or actor.id == current_owner_id):
            return await interaction.response.send_message("Only the owner (or an Administrator) can transfer.", ephemeral=True)

        overwrites = vc.overwrites

        old_owner = interaction.guild.get_member(current_owner_id)
        if old_owner:
            ow = overwrites.get(old_owner, discord.PermissionOverwrite())
            ow.manage_channels = False
            ow.move_members = False
            ow.mute_members = False
            ow.deafen_members = False
            overwrites[old_owner] = ow

        ow2 = overwrites.get(new_owner, discord.PermissionOverwrite())
        ow2.view_channel = True
        ow2.connect = True
        ow2.manage_channels = True
        ow2.move_members = True
        ow2.mute_members = True
        ow2.deafen_members = True
        overwrites[new_owner] = ow2

        mod_role = get_mod_role(interaction.guild)
        if mod_role:
            m = overwrites.get(mod_role, discord.PermissionOverwrite())
            m.view_channel = True
            m.connect = True
            overwrites[mod_role] = m

        await vc.edit(overwrites=overwrites, reason="Transfer ownership")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_vcs SET owner_id=? WHERE guild_id=? AND channel_id=?",
                (new_owner.id, interaction.guild.id, vc.id),
            )
            await db.commit()

        await interaction.response.send_message(f"Ownership transferred to {new_owner.mention}.", ephemeral=True)


class ReportUserModal(discord.ui.Modal, title="Report User"):  # type: ignore
    """Pre-filled complaint modal for reporting a user (reuses complaint_modal flow)."""
    def __init__(self, member: discord.Member):
        super().__init__(timeout=300, custom_id="complaint_modal")
        ctx = f"Reported user: {member.mention} (ID: {member.id})\n\n"
        self.category = discord.ui.TextInput(
            label="Category",
            placeholder="harassment / spam / voice conduct / etc.",
            max_length=60,
            default="User Report",
            custom_id="category"
        )
        self.details = discord.ui.TextInput(
            label="Details",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            default=ctx + "[Please describe what happened]",
            custom_id="details"
        )
        self.evidence = discord.ui.TextInput(
            label="Evidence (optional link)",
            required=False,
            max_length=200,
            custom_id="evidence"
        )
        self.add_item(self.category)
        self.add_item(self.details)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass


class ReportMessageModal(discord.ui.Modal, title="Report Message"):  # type: ignore
    """Pre-filled complaint modal for reporting a message (reuses complaint_modal flow)."""
    def __init__(self, message: discord.Message):
        super().__init__(timeout=300, custom_id="complaint_modal")
        content = (message.content or "[no text]")[:300]
        if len((message.content or "")) > 300:
            content += "..."
        ctx = f"Reported message: {message.jump_url}\nAuthor: {message.author.mention}\nContent: {content}\n\n"
        self.category = discord.ui.TextInput(
            label="Category",
            placeholder="spam / harassment / rule violation / etc.",
            max_length=60,
            default="Message Report",
            custom_id="category"
        )
        self.details = discord.ui.TextInput(
            label="Details",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            default=ctx + "[Please describe why you're reporting]",
            custom_id="details"
        )
        self.evidence = discord.ui.TextInput(
            label="Evidence (optional link)",
            required=False,
            max_length=200,
            custom_id="evidence"
        )
        self.add_item(self.category)
        self.add_item(self.details)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass


class AddToSuggestionModal(discord.ui.Modal, title="Add to Suggestions"):  # type: ignore
    """Modal to turn a message into a suggestion (from message context menu)."""
    def __init__(self, message: discord.Message):
        super().__init__(timeout=300, custom_id="add_to_suggestion_modal")
        default = (message.content or "").strip()[:1900] or "[Add your suggestion here]"
        self.suggestion = discord.ui.TextInput(
            label="Suggestion text",
            style=discord.TextStyle.paragraph,
            default=default,
            max_length=2000,
            custom_id="suggestion"
        )
        self.category = discord.ui.TextInput(
            label="Category",
            placeholder="feature / bug / improvement / other",
            default="other",
            max_length=20,
            custom_id="category"
        )
        self.add_item(self.suggestion)
        self.add_item(self.category)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from commands.suggestions.suggest import create_suggestion_from_modal
        text = (self.suggestion.value or "").strip()
        cat = (self.category.value or "other").strip().lower() or "other"
        await create_suggestion_from_modal(interaction, text, cat)


class AddAsEventModal(discord.ui.Modal, title="Add as Event"):  # type: ignore
    """Modal to create event from message content (context menu)."""
    def __init__(self, message: discord.Message):
        super().__init__(timeout=300, custom_id="add_as_event_modal")
        content = (message.content or "").strip()[:200]
        first_line = content.split("\n")[0][:80] if content else "Event"
        self.title_input = discord.ui.TextInput(label="Event title", default=first_line, max_length=100, custom_id="title")
        self.when_input = discord.ui.TextInput(label="When", default="tomorrow 8pm", max_length=60, custom_id="when")
        self.desc_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, default=content[:1000], max_length=1000, custom_id="desc")
        self.add_item(self.title_input)
        self.add_item(self.when_input)
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        from commands.events.event_create import create_event_from_modal
        await create_event_from_modal(interaction, self.title_input.value, self.when_input.value, self.desc_input.value)


class CreateTicketForUserModal(discord.ui.Modal, title="Create Ticket for User"):  # type: ignore
    """Modal for mods to create a ticket on behalf of a user."""
    def __init__(self, member: discord.Member):
        super().__init__(timeout=300, custom_id="create_ticket_for_user_modal")
        self.target_member = member
        self.subject = discord.ui.TextInput(label="Subject", placeholder="e.g. Help with application", max_length=100, custom_id="subject")
        self.add_item(self.subject)

    async def on_submit(self, interaction: discord.Interaction):
        from commands.tickets.ticket import create_ticket_for_user
        await create_ticket_for_user(interaction, self.target_member, self.subject.value or "Support")


class ComplaintModal(discord.ui.Modal, title="File Complaint"):  # type: ignore
    def __init__(self):
        super().__init__(timeout=300, custom_id="complaint_modal")
        
        self.category = discord.ui.TextInput(
            label="Category", 
            placeholder="harassment / trade / voice conduct / etc.", 
            max_length=60,
            custom_id="category"
        )
        self.details = discord.ui.TextInput(
            label="Details", 
            style=discord.TextStyle.paragraph, 
            max_length=1000,
            custom_id="details"
        )
        self.evidence = discord.ui.TextInput(
            label="Evidence (optional link)", 
            required=False, 
            max_length=200,
            custom_id="evidence"
        )
        
        self.add_item(self.category)
        self.add_item(self.details)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        # This method defers the interaction to prevent expiration, but actual processing
        # is handled by the on_interaction handler for persistence after bot restarts.
        # We defer unconditionally (if possible) - on_interaction will check is_done() before deferring
        logger.info(f"[modal] ComplaintModal.on_submit: Attempting to defer (on_interaction will process)")
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info(f"[modal] ComplaintModal.on_submit: Successfully deferred")
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
            # Interaction already handled or expired - on_interaction may have gotten it first
            logger.info(f"[modal] ComplaintModal.on_submit: Could not defer: {e}")
        # Don't process here - let on_interaction handle it
        return


class RequestInfoModal(discord.ui.Modal, title="Request Evidence"):  # type: ignore
    def __init__(self, case_id: str):
        super().__init__(timeout=300, custom_id=f"request_info_{case_id}")
        self.case_id = case_id
        
        self.question = discord.ui.TextInput(
            label="Question to ask the user", 
            style=discord.TextStyle.paragraph, 
            max_length=800,
            custom_id="question"
        )
        self.add_item(self.question)

    async def on_submit(self, interaction: discord.Interaction):
        # This method defers the interaction to prevent expiration, but actual processing
        # is handled by the on_interaction handler for persistence after bot restarts.
        # We defer unconditionally (if possible) - on_interaction will check is_done() before deferring
        logger.info(f"[modal] RequestInfoModal.on_submit: Attempting to defer (on_interaction will process)")
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info(f"[modal] RequestInfoModal.on_submit: Successfully deferred")
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
            # Interaction already handled or expired - on_interaction may have gotten it first
            logger.info(f"[modal] RequestInfoModal.on_submit: Could not defer: {e}")
        # Don't process here - let on_interaction handle it
        return


class ApplicationQuestionModal(discord.ui.Modal, title="Add Application Question"):  # type: ignore
    def __init__(self, guild_id: int):
        super().__init__(timeout=300, custom_id=f"application_question_{guild_id}")
        self.guild_id = guild_id
        
        self.question_text = discord.ui.TextInput(
            label="Question",
            style=discord.TextStyle.paragraph,
            placeholder="e.g., Why do you want to join our clan?",
            max_length=500,
            custom_id="question_text"
        )
        self.add_item(self.question_text)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        question_text = str(self.question_text).strip()
        if not question_text:
            return await interaction.followup.send("Question cannot be empty.", ephemeral=True)
        
        # Get the next question order
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT MAX(question_order) FROM application_questions WHERE guild_id = ?
            """, (self.guild_id,))
            row = await cur.fetchone()
            next_order = (row[0] or 0) + 1
            
            await db.execute("""
                INSERT INTO application_questions (guild_id, question_order, question_text)
                VALUES (?, ?, ?)
            """, (self.guild_id, next_order, question_text))
            await db.commit()
        
        from core.utils import obsidian_embed
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Question Added",
                f"Question {next_order} has been added:\n\n{question_text}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )


class ApplicationRejectModal(discord.ui.Modal, title="Reject Application"):  # type: ignore
    def __init__(self, application_id: int):
        super().__init__(timeout=300, custom_id=f"application_reject_{application_id}")
        self.application_id = application_id
        
        self.reason = discord.ui.TextInput(
            label="Rejection Reason (optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Provide a reason for rejection (optional)...",
            required=False,
            max_length=500,
            custom_id="reason"
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        reason = str(self.reason).strip() if self.reason.value else None
        
        # Update application status
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE applications
                SET status = 'REJECTED', reviewed_by = ?, reviewed_at = ?, review_note = ?
                WHERE id = ?
            """, (interaction.user.id, now_utc().isoformat(), reason, self.application_id))
            await db.commit()
            
            # Get user_id
            cur = await db.execute("SELECT user_id FROM applications WHERE id = ?", (self.application_id,))
            row = await cur.fetchone()
            user_id = row[0] if row else None
        
        # Update embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        # Update status field
        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.set_field_at(i, name="Status", value="❌ Rejected", inline=True)
                break
        
        if reason:
            embed.add_field(name="Rejection Reason", value=reason, inline=False)
        
        # Disable buttons - get the view from the message
        if interaction.message.components:
            # Disable all buttons in the existing view
            view = discord.ui.View.from_message(interaction.message)
            for item in view.children:
                item.disabled = True
            await interaction.message.edit(embed=embed, view=view)
        else:
            await interaction.message.edit(embed=embed)
        
        dm_ok = True
        if user_id:
            user = interaction.guild.get_member(user_id)
            if user:
                dm_ok = False
                try:
                    rejection_msg = f"Your application to join {interaction.guild.name} wasn't approved this time."
                    if reason:
                        rejection_msg += f"\n\n**Reason:** {reason}"

                    await user.send(
                        embed=obsidian_embed(
                            "Application update",
                            rejection_msg,
                            color=discord.Color.orange(),
                            client=interaction.client,
                        )
                    )
                    dm_ok = True
                except discord.Forbidden:
                    pass

        mod_note = "Application rejected."
        if user_id and not dm_ok:
            mod_note += " **Couldn't DM the applicant** — they may have DMs off; consider letting them know in-channel."
        await interaction.followup.send(mod_note, ephemeral=True)


class ApplicationResponseModal(discord.ui.Modal, title="Application Question"):  # type: ignore
    def __init__(self, application_id: int, question_id: int, question_text: str):
        super().__init__(timeout=600, custom_id=f"application_response_{application_id}_{question_id}")
        self.application_id = application_id
        self.question_id = question_id
        
        # Ensure label is between 1 and 45 characters
        # Discord requires labels to be 1-45 characters
        if not question_text or len(question_text.strip()) == 0:
            label = "Your Answer"
        elif len(question_text) <= 45:
            label = question_text
        else:
            # Truncate to 42 characters and add "..." (total 45)
            label = question_text[:42] + "..."
        
        # Create a text input for the response
        self.response = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph,
            placeholder="Type your answer here...",
            max_length=1000,
            custom_id="response"
        )
        self.add_item(self.response)

    async def on_submit(self, interaction: discord.Interaction):
        # This will be handled in bot.py's on_interaction handler
        logger.info(f"[modal] ApplicationResponseModal.on_submit: Deferring (on_interaction will process)")
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            pass
        return
