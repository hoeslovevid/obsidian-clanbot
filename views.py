"""
View classes for Discord interactions.
This module contains all View classes used by the bot.
"""
import logging
import discord
import aiosqlite  # type: ignore
from typing import Optional

from utils import is_mod, display_case_status, obsidian_embed
from database import DB_PATH, now_utc, log_complaint_action

logger = logging.getLogger(__name__)


class SetLimitSelect(discord.ui.Select):
    def __init__(self, vc_id: int):
        options = [
            discord.SelectOption(label="No limit", value="0"),
            discord.SelectOption(label="2", value="2"),
            discord.SelectOption(label="3", value="3"),
            discord.SelectOption(label="4", value="4"),
            discord.SelectOption(label="6", value="6"),
            discord.SelectOption(label="8", value="8"),
            discord.SelectOption(label="10", value="10"),
            discord.SelectOption(label="12", value="12"),
        ]
        super().__init__(
            placeholder="Set cell capacity…",
            options=options,
            custom_id=f"vc:{vc_id}:setlimit",
        )
        self.vc_id = vc_id

    async def callback(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        try:
            limit = int(self.values[0])
        except ValueError:
            return await interaction.response.send_message("Invalid limit.", ephemeral=True)

        await vc.edit(user_limit=limit, reason="Obsidian VC limit")
        await interaction.response.send_message("Limit updated.", ephemeral=True)


class SetLimitView(discord.ui.View):
    def __init__(self, vc_id: int):
        super().__init__(timeout=120)
        self.add_item(SetLimitSelect(vc_id))


class VCPanelView(discord.ui.View):
    """
    Persistent view per VC (custom_ids include vc_id to avoid collisions).
    We re-register these views on startup for existing temp VCs in the DB.
    """

    def __init__(self, vc_id: int):
        super().__init__(timeout=None)
        self.vc_id = vc_id

        self.add_item(discord.ui.Button(label="Recalibrate", style=discord.ButtonStyle.primary, emoji="✒️", custom_id=f"vc:{vc_id}:rename"))
        self.add_item(discord.ui.Button(label="Capacity", style=discord.ButtonStyle.secondary, emoji="👥", custom_id=f"vc:{vc_id}:limit"))
        self.add_item(discord.ui.Button(label="Seal", style=discord.ButtonStyle.danger, emoji="🔒", custom_id=f"vc:{vc_id}:lock"))
        self.add_item(discord.ui.Button(label="Unseal", style=discord.ButtonStyle.success, emoji="🔓", custom_id=f"vc:{vc_id}:unlock"))
        self.add_item(discord.ui.Button(label="Cloak", style=discord.ButtonStyle.danger, emoji="🫥", custom_id=f"vc:{vc_id}:hide"))
        self.add_item(discord.ui.Button(label="Reveal", style=discord.ButtonStyle.success, emoji="👁️", custom_id=f"vc:{vc_id}:show"))
        self.add_item(discord.ui.Button(label="Grant", style=discord.ButtonStyle.secondary, emoji="➕", custom_id=f"vc:{vc_id}:invite"))
        self.add_item(discord.ui.Button(label="Revoke", style=discord.ButtonStyle.secondary, emoji="⛓️", custom_id=f"vc:{vc_id}:remove"))
        self.add_item(discord.ui.Button(label="Pass Command", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id=f"vc:{vc_id}:transfer"))
        self.add_item(discord.ui.Button(label="Dissolve", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id=f"vc:{vc_id}:disband"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only owner or mods can use most controls
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if is_mod(member):
            return True

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, self.vc_id),
            )
            row = await cur.fetchone()
        return bool(row and int(row[0]) == member.id)

    async def on_timeout(self):
        return


class ComplaintPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Seal a Report",
                style=discord.ButtonStyle.danger,
                emoji="🩸",
                custom_id="complaints:open",
            )
        )


class ComplaintModView(discord.ui.View):
    """
    Persistent per case (custom_ids include case_id).
    We re-register for OPEN/ACK/NEEDS INFO cases on startup.
    """

    def __init__(self, case_id: str):
        super().__init__(timeout=None)
        self.case_id = case_id

        self.add_item(discord.ui.Button(label="Mark Reviewed", style=discord.ButtonStyle.primary, emoji="✅", custom_id=f"complaints:{case_id}:ack"))
        self.add_item(discord.ui.Button(label="Close Docket", style=discord.ButtonStyle.success, emoji="🔒", custom_id=f"complaints:{case_id}:resolve"))
        self.add_item(discord.ui.Button(label="Dismiss", style=discord.ButtonStyle.secondary, emoji="❌", custom_id=f"complaints:{case_id}:reject"))
        self.add_item(discord.ui.Button(label="Request Evidence", style=discord.ButtonStyle.danger, emoji="❗", custom_id=f"complaints:{case_id}:needinfo"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_mod(member)

    async def dm_user(self, guild: discord.Guild, user_id: int, status: str, bot):
        user = guild.get_member(user_id) or await bot.fetch_user(user_id)
        if not user:
            return
        try:
            e = obsidian_embed(f"Docket Update • {self.case_id}", f"Status: **{display_case_status(status)}**", client=bot)
            await user.send(embed=e)
        except discord.Forbidden:
            pass

    async def set_status(self, interaction: discord.Interaction, status: str, bot, *, dm_override: bool = True) -> Optional[int]:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, self.case_id),
            )
            row = await cur.fetchone()
            if not row:
                return None
            user_id = int(row[0])

            await db.execute(
                "UPDATE complaints SET status=?, last_update_at=? WHERE guild_id=? AND case_id=?",
                (status, now_utc().isoformat(), interaction.guild.id, self.case_id),
            )
            await db.commit()

        if dm_override:
            await self.dm_user(interaction.guild, user_id, status, bot)

        await log_complaint_action(interaction.guild.id, self.case_id, interaction.user.id, f"STATUS:{status}")
        return user_id


class RSVPView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Going", style=discord.ButtonStyle.success, emoji="✅", custom_id="events:rsvp:going"))
        self.add_item(discord.ui.Button(label="Maybe", style=discord.ButtonStyle.primary, emoji="❔", custom_id="events:rsvp:maybe"))
        self.add_item(discord.ui.Button(label="Can't", style=discord.ButtonStyle.danger, emoji="❌", custom_id="events:rsvp:no"))

    async def _set_rsvp(self, interaction: discord.Interaction, response: str):
        guild_id = interaction.guild.id
        msg_id = interaction.message.id

        async with aiosqlite.connect(DB_PATH) as db:
            # Check if this is a new RSVP (not just updating)
            cur = await db.execute(
                "SELECT response FROM event_rsvps WHERE guild_id=? AND message_id=? AND user_id=?",
                (guild_id, msg_id, interaction.user.id),
            )
            existing = await cur.fetchone()
            is_new_rsvp = existing is None or existing[0] != response
            
            await db.execute(
                "INSERT INTO event_rsvps(guild_id,message_id,user_id,response) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id,message_id,user_id) DO UPDATE SET response=excluded.response",
                (guild_id, msg_id, interaction.user.id, response),
            )
            await db.commit()

            cur = await db.execute(
                "SELECT response, COUNT(*) FROM event_rsvps WHERE guild_id=? AND message_id=? GROUP BY response",
                (guild_id, msg_id),
            )
            rows = await cur.fetchall()

        # Track event attendance if RSVPing "GOING"
        if is_new_rsvp and response == "GOING":
            try:
                from database import track_event_attendance
                await track_event_attendance(guild_id, interaction.user.id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"Failed to track event attendance: {e}")

        counts = {"GOING": 0, "MAYBE": 0, "NO": 0}
        for r, c in rows:
            counts[str(r)] = int(c)

        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"✅ {counts['GOING']}  |  ❔ {counts['MAYBE']}  |  ❌ {counts['NO']}")
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("RSVP recorded.", ephemeral=True)


class TradingPostView(discord.ui.View):
    """View for managing trading posts."""
    def __init__(self, listing_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.listing_id = listing_id
        self.owner_id = owner_id
        
        # Add buttons with custom_id for persistence
        sold_button = discord.ui.Button(label="Mark as Sold", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"trade:{listing_id}:sold")
        sold_button.callback = self.mark_sold_button
        self.add_item(sold_button)
        
        delete_button = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id=f"trade:{listing_id}:delete")
        delete_button.callback = self.delete_button
        self.add_item(delete_button)
    
    async def mark_sold_button(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the listing owner can mark it as sold.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE trading_posts
                SET status = 'SOLD', updated_at = ?
                WHERE id = ?
            """, (now_utc().isoformat(), self.listing_id))
            await db.commit()
        
        # Update embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.grey()
        # Update status
        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.set_field_at(i, name="Status", value="✅ Sold", inline=True)
                break
        else:
            embed.add_field(name="Status", value="✅ Sold", inline=True)
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send("Listing marked as sold.", ephemeral=True)
    
    async def delete_button(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the listing owner can delete it.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE trading_posts
                SET status = 'DELETED', updated_at = ?
                WHERE id = ?
            """, (now_utc().isoformat(), self.listing_id))
            await db.commit()
        
        try:
            await interaction.message.delete()
            await interaction.followup.send("Listing deleted.", ephemeral=True)
        except discord.NotFound:
            await interaction.followup.send("Listing deleted.", ephemeral=True)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error deleting trade listing message: {e}")
            await interaction.followup.send("Listing marked as deleted (message could not be removed).", ephemeral=True)


class ApplicationManageView(discord.ui.View):
    """View for moderators to manage applications."""
    def __init__(self, application_id: int):
        super().__init__(timeout=None)
        self.application_id = application_id
        
        # Add buttons with custom_id for persistence
        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"application:{application_id}:approve")
        approve_button.callback = self.approve_button
        self.add_item(approve_button)
        
        reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id=f"application:{application_id}:reject")
        reject_button.callback = self.reject_button
        self.add_item(reject_button)
    
    async def approve_button(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Only moderators can use this.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        # Update application status
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE applications
                SET status = 'APPROVED', reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
            """, (interaction.user.id, now_utc().isoformat(), self.application_id))
            await db.commit()
            
            # Get user_id
            cur = await db.execute("SELECT user_id FROM applications WHERE id = ?", (self.application_id,))
            row = await cur.fetchone()
            user_id = row[0] if row else None
        
        # Update embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        # Update status field
        for i, field in enumerate(embed.fields):
            if field.name == "Status":
                embed.set_field_at(i, name="Status", value="✅ Approved", inline=True)
                break
        
        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        
        # Notify user
        if user_id:
            user = interaction.guild.get_member(user_id)
            if user:
                try:
                    await user.send(
                        embed=obsidian_embed(
                            "✅ Application Approved",
                            f"Congratulations! Your application to join {interaction.guild.name} has been approved.",
                            color=discord.Color.green(),
                            client=interaction.client,
                        )
                    )
                except discord.Forbidden:
                    pass
        
        await interaction.followup.send("Application approved.", ephemeral=True)
    
    async def reject_button(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Only moderators can use this.", ephemeral=True)
        
        # Show modal for rejection reason
        from modals import ApplicationRejectModal
        modal = ApplicationRejectModal(self.application_id)
        await interaction.response.send_modal(modal)
