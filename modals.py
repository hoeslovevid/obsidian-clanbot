"""
Modal classes for Discord interactions.
This module contains all Modal classes used by the bot.
"""
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Optional

from utils import extract_id, get_mod_role, is_mod, MOD_ROLE_NAME
from database import DB_PATH

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
