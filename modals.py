"""
Modal classes for Discord interactions.
This module contains all Modal classes used by the bot.
"""
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Optional

from utils import extract_id, get_mod_role, is_mod, MOD_ROLE_NAME, obsidian_embed
from database import DB_PATH, now_utc

logger = logging.getLogger(__name__)


class RenameVCModal(discord.ui.Modal, title="Recalibrate Comms Node"):  # type: ignore
    new_name = discord.ui.TextInput(label="New designation", max_length=80)

    def __init__(self, vc_id: int):
        super().__init__(timeout=300)
        self.vc_id = vc_id

    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        await vc.edit(name=str(self.new_name), reason="Obsidian VC rename")
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
        await vc.edit(overwrites=overwrites, reason="Obsidian VC invite")
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
            await vc.edit(overwrites=overwrites, reason="Obsidian VC remove access")
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
            return await interaction.response.send_message("Only the owner (or Obsidian Inheritor) can transfer.", ephemeral=True)

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

        await vc.edit(overwrites=overwrites, reason="Obsidian transfer ownership")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE temp_vcs SET owner_id=? WHERE guild_id=? AND channel_id=?",
                (new_owner.id, interaction.guild.id, vc.id),
            )
            await db.commit()

        await interaction.response.send_message(f"Ownership transferred to {new_owner.mention}.", ephemeral=True)


class ComplaintModal(discord.ui.Modal, title="Obsidian Docket Submission"):  # type: ignore
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
        
        from utils import obsidian_embed
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
        
        # Notify user
        if user_id:
            user = interaction.guild.get_member(user_id)
            if user:
                try:
                    rejection_msg = f"Your application to join {interaction.guild.name} has been rejected."
                    if reason:
                        rejection_msg += f"\n\n**Reason:** {reason}"
                    
                    await user.send(
                        embed=obsidian_embed(
                            "❌ Application Rejected",
                            rejection_msg,
                            color=discord.Color.red(),
                            client=interaction.client,
                        )
                    )
                except discord.Forbidden:
                    pass
        
        await interaction.followup.send("Application rejected.", ephemeral=True)


class ApplicationResponseModal(discord.ui.Modal, title="Application Question"):  # type: ignore
    def __init__(self, application_id: int, question_id: int, question_text: str):
        super().__init__(timeout=600, custom_id=f"application_response_{application_id}_{question_id}")
        self.application_id = application_id
        self.question_id = question_id
        
        # Create a text input for the response
        self.response = discord.ui.TextInput(
            label=question_text[:45] + "..." if len(question_text) > 45 else question_text,
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
