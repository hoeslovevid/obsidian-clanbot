"""
View classes for Discord interactions.
This module contains all View classes used by the bot.
"""
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Optional, Callable, Awaitable, Any

from utils import is_mod, display_case_status, obsidian_embed
from database import DB_PATH, now_utc, log_complaint_action

logger = logging.getLogger(__name__)


class EmbedPaginator(discord.ui.View):
    """Reusable paginated embed view with Prev/Next buttons."""

    def __init__(self, title: str, pages: list, *, color=None, client=None, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.title = title
        self.pages = pages
        self.color = color or discord.Color.blue()
        self.client = client
        self.page = 0
        self.total_pages = max(1, len(pages))
        self._update_buttons()

    def _update_buttons(self):
        for c in self.children:
            if getattr(c, "custom_id", "") == "paginator_prev":
                c.disabled = self.page <= 0
            elif getattr(c, "custom_id", "") == "paginator_next":
                c.disabled = self.page >= self.total_pages - 1

    def _build_embed(self) -> discord.Embed:
        p = self.pages[self.page]
        desc = p.get("description", "")
        fields = p.get("fields", [])
        footer = p.get("footer") or f"Page {self.page + 1}/{self.total_pages}"
        return obsidian_embed(
            self.title,
            desc,
            color=self.color,
            fields=fields if fields else None,
            footer=footer,
            client=self.client,
        )

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="paginator_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="paginator_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


class RetryView(discord.ui.View):
    """View with Retry button for flaky operations (e.g. API failures)."""

    def __init__(self, retry_callback, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.retry_callback = retry_callback

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.primary, emoji="🔄")
    async def retry_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await self.retry_callback(interaction)


class RefreshView(discord.ui.View):
    """View with Refresh button to invalidate cache and refetch (e.g. cycles, Baro)."""

    def __init__(self, refresh_callback, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.refresh_callback = refresh_callback

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await self.refresh_callback(interaction)


class ConfirmView(discord.ui.View):
    """Reusable confirmation view with Confirm/Cancel buttons."""

    def __init__(self, callback: Callable[[discord.Interaction, bool], Awaitable[Any]], *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.callback_fn = callback

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await self.callback_fn(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            pass
        await self.callback_fn(interaction, False)

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        try:
            if self.message:
                await self.message.edit(
                    content="⏰ Timed out. Please run the command again.",
                    embed=None,
                    view=self,
                )
        except Exception:
            pass


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

        await vc.edit(user_limit=limit, reason="VC limit")
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

    async def set_status(self, interaction: discord.Interaction, status: str, *, bot, dm_override: bool = True) -> Optional[int]:
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

        await log_complaint_action(interaction.guild.id, self.case_id, interaction.user.id, f"STATUS:{status}", guild=interaction.guild, bot=bot)
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


class GiveawayView(discord.ui.View):
    """View for giveaway enter/leave buttons."""
    def __init__(self, giveaway_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
    
    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.green, emoji="🎉", custom_id="giveaway:enter")
    async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Enter a giveaway."""
        if not self.giveaway_id:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Error",
                    "Giveaway ID not found. Please contact a moderator.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get giveaway info
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, prize, winner_count, end_time, ended, required_role_id, min_level
                FROM giveaways WHERE id = ?
            """, (self.giveaway_id,))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Giveaway Not Found",
                    "This giveaway no longer exists.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        giveaway_id, prize, winner_count, end_time_str, ended, required_role_id, min_level = row
        
        # Check if ended
        if ended:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Giveaway Ended",
                    "This giveaway has already ended.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check requirements
        if required_role_id:
            role = interaction.guild.get_role(required_role_id)
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Requirement Not Met",
                        f"You need the {role.mention} role to enter this giveaway.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        if min_level:
            from database import get_user_xp
            _, user_level, _ = await get_user_xp(interaction.guild.id, interaction.user.id)
            if user_level < min_level:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Level Requirement",
                        f"You need to be at least level {min_level} to enter this giveaway. Your current level: {user_level}",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Check if already entered
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?
            """, (giveaway_id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "ℹ️ Already Entered",
                    f"You have already entered this giveaway for **{prize}**.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Add entry
            await db.execute("""
                INSERT INTO giveaway_entries (giveaway_id, user_id, entered_at)
                VALUES (?, ?, ?)
            """, (giveaway_id, interaction.user.id, now_utc().isoformat()))
            await db.commit()
            
            # Get entry count
            cur = await db.execute("""
                SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?
            """, (giveaway_id,))
            entry_count = (await cur.fetchone())[0]
        
        # Update embed
        try:
            message = interaction.message
            if message and message.embeds:
                embed = message.embeds[0]
                # Update entry count in description
                desc = embed.description
                if "**Entries:**" in desc:
                    desc = desc.rsplit("**Entries:**", 1)[0] + f"**Entries:** {entry_count}"
                else:
                    desc += f"\n\n**Entries:** {entry_count}"
                embed.description = desc
                await message.edit(embed=embed)
        except Exception as e:
            logger.debug(f"Could not update giveaway embed: {e}")
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Entered Giveaway",
                f"You have entered the giveaway for **{prize}**!\n\n"
                f"**Entries:** {entry_count}",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    @discord.ui.button(label="Leave Giveaway", style=discord.ButtonStyle.red, emoji="❌", custom_id="giveaway:leave")
    async def leave_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave a giveaway."""
        if not self.giveaway_id:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Error",
                    "Giveaway ID not found. Please contact a moderator.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get giveaway info
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, prize, ended FROM giveaways WHERE id = ?
            """, (self.giveaway_id,))
            row = await cur.fetchone()
        
        if not row:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Giveaway Not Found",
                    "This giveaway no longer exists.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        giveaway_id, prize, ended = row
        
        # Check if ended
        if ended:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Giveaway Ended",
                    "This giveaway has already ended.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check if entered
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?
            """, (giveaway_id, interaction.user.id))
            await db.commit()
            
            if cur.rowcount == 0:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "ℹ️ Not Entered",
                        "You are not entered in this giveaway.",
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Get entry count
            cur = await db.execute("""
                SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?
            """, (giveaway_id,))
            entry_count = (await cur.fetchone())[0]
        
        # Update embed
        try:
            message = interaction.message
            if message and message.embeds:
                embed = message.embeds[0]
                desc = embed.description
                if "**Entries:**" in desc:
                    desc = desc.rsplit("**Entries:**", 1)[0] + f"**Entries:** {entry_count}"
                else:
                    desc += f"\n\n**Entries:** {entry_count}"
                embed.description = desc
                await message.edit(embed=embed)
        except Exception as e:
            logger.debug(f"Could not update giveaway embed: {e}")
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Left Giveaway",
                f"You have left the giveaway for **{prize}**.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )


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
        
        # Notify user and assign role
        role_assigned = False
        if user_id:
            user = interaction.guild.get_member(user_id)
            if user:
                # Assign Oathtaker role
                oathtaker_role = discord.utils.get(interaction.guild.roles, name="Oathtaker")
                if oathtaker_role:
                    try:
                        # Check if bot has permission to manage roles
                        if interaction.guild.me.guild_permissions.manage_roles:
                            # Check if bot's role is high enough
                            if interaction.guild.me.top_role > oathtaker_role:
                                if oathtaker_role not in user.roles:
                                    await user.add_roles(oathtaker_role, reason="Application approved")
                                    role_assigned = True
                                    logger.info(f"[application] Assigned Oathtaker role to {user} after application approval")
                                else:
                                    role_assigned = True  # Already has the role
                            else:
                                logger.warning(f"[application] Bot's role is not high enough to assign Oathtaker role to {user}")
                        else:
                            logger.warning(f"[application] Bot does not have permission to manage roles")
                    except discord.Forbidden:
                        logger.warning(f"[application] No permission to assign Oathtaker role to {user}")
                    except Exception as e:
                        logger.error(f"[application] Error assigning Oathtaker role: {e}")
                else:
                    logger.warning(f"[application] Oathtaker role not found in guild {interaction.guild.id}")
                
                # Send DM notification
                try:
                    message_text = f"Congratulations! Your application to join {interaction.guild.name} has been approved."
                    if role_assigned:
                        message_text += "\n\nYou have been assigned the **Oathtaker** role!"
                    
                    await user.send(
                        embed=obsidian_embed(
                            "✅ Application Approved",
                            message_text,
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


class ApplicationPanelView(discord.ui.View):
    """View with button to start an application."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        
        # Add button with custom_id for persistence
        apply_button = discord.ui.Button(
            label="Start Application",
            style=discord.ButtonStyle.primary,
            emoji="📝",
            custom_id=f"application_panel:{guild_id}:start"
        )
        apply_button.callback = self.start_application
        self.add_item(apply_button)
    
    async def start_application(self, interaction: discord.Interaction):
        """Handle application start from button."""
        # Defer immediately to acknowledge the button click
        # This must be done before any async operations to avoid timeout
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
            # Already handled or expired, will use followup
            pass
        
        # Import the application start logic
        from commands.applications.application import start_application_process
        await start_application_process(interaction)
