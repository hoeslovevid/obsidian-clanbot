"""
View classes for Discord interactions.
This module contains all View classes used by the bot.
"""
import logging
import discord  # type: ignore
import aiosqlite  # type: ignore
from typing import Optional, Callable, Awaitable, Any, Tuple

from core.utils import display_case_status, is_mod, obsidian_embed, render_bar, error_embed, success_embed
from core.vc_permissions import can_manage_temp_vc
from database import DB_PATH, now_utc, log_complaint_action

logger = logging.getLogger(__name__)


async def _interaction_followup_ephemeral(interaction: discord.Interaction, content: str) -> None:
    try:
        await interaction.followup.send(content, ephemeral=True)
    except discord.HTTPException:
        pass


async def _reenable_view_buttons(interaction: discord.Interaction, view: discord.ui.View) -> None:
    for c in view.children:
        c.disabled = False
    try:
        if interaction.message:
            await interaction.message.edit(view=view)
    except Exception:
        pass


async def _update_giveaway_entry_embed(message: discord.Message, entry_count: int) -> None:
    """Update public giveaway embed entry count; skip if unchanged."""
    if not message or not message.embeds:
        return
    embed = message.embeds[0].copy()
    desc = embed.description or ""
    import re

    match = re.search(r"\*\*Entries:\*\*\s*(\d+)", desc)
    if match and int(match.group(1)) == entry_count:
        return
    if "**Entries:**" in desc:
        desc = desc.rsplit("**Entries:**", 1)[0] + f"**Entries:** {entry_count}"
    else:
        desc += f"\n\n**Entries:** {entry_count}"
    embed.description = desc
    from core.safe_message_edit import safe_message_edit

    await safe_message_edit(message, embed=embed)


class EmbedPaginator(discord.ui.View):
    """Reusable paginated embed view with Prev/Next buttons."""

    def __init__(self, title: str, pages: list, *, color=None, client=None, timeout: float = 300, total_items: int = None, per_page: int = 15):
        super().__init__(timeout=timeout)
        self.title = title
        self.pages = pages
        self.color = color or discord.Color.blue()
        self.client = client
        self.page = 0
        self.total_pages = max(1, len(pages))
        self._total_items = total_items
        self._per_page = per_page
        self._update_buttons()

    def _update_buttons(self):
        at_start = self.page <= 0
        at_end = self.page >= self.total_pages - 1
        for c in self.children:
            cid = getattr(c, "custom_id", "")
            if cid == "paginator_first":
                c.disabled = at_start or self.total_pages <= 2
            elif cid == "paginator_prev":
                c.disabled = at_start
            elif cid == "paginator_next":
                c.disabled = at_end
            elif cid == "paginator_last":
                c.disabled = at_end or self.total_pages <= 2
            elif cid == "paginator_jump":
                # Jumping only makes sense with 3+ pages.
                c.disabled = self.total_pages <= 2

    def _build_embed(self) -> discord.Embed:
        p = self.pages[self.page]
        desc = p.get("description", "")
        fields = p.get("fields", [])
        total_items = self._total_items
        if total_items is not None:
            per_page = getattr(self, "_per_page", 15)
            start = self.page * per_page + 1
            end = min((self.page + 1) * per_page, total_items)
            footer = f"Page {self.page + 1}/{self.total_pages} • Showing {start}-{end} of {total_items}"
        else:
            footer = p.get("footer") or f"Page {self.page + 1}/{self.total_pages}"
        return obsidian_embed(
            self.title,
            desc,
            color=self.color,
            fields=fields if fields else None,
            footer=footer,
            thumbnail=p.get("thumbnail"),
            client=self.client,
        )

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        try:
            if self.message:
                emb = self._build_embed()
                emb.set_footer(text=(emb.footer.text or "") + " • ⏰ Session expired")
                await self.message.edit(embed=emb, view=self)
        except Exception:
            pass

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary, custom_id="paginator_first")
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

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

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary, custom_id="paginator_last")
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = self.total_pages - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Jump", emoji="🔢", style=discord.ButtonStyle.secondary, custom_id="paginator_jump")
    async def jump_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_PageJumpModal(self))


class _PageJumpModal(discord.ui.Modal, title="Jump to page"):
    """Modal to jump directly to a page in an EmbedPaginator."""

    def __init__(self, paginator: "EmbedPaginator"):
        super().__init__(timeout=120)
        self.paginator = paginator
        self.page_input = discord.ui.TextInput(
            label=f"Page number (1-{paginator.total_pages})",
            placeholder=f"Enter 1-{paginator.total_pages}",
            required=True,
            max_length=6,
        )
        self.add_item(self.page_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = (self.page_input.value or "").strip()
        if not raw.lstrip("+-").isdigit():
            return await interaction.response.send_message(
                f"'{raw}' isn't a number. Enter a page between 1 and {self.paginator.total_pages}.",
                ephemeral=True,
            )
        target = max(1, min(self.paginator.total_pages, int(raw)))
        self.paginator.page = target - 1
        self.paginator._update_buttons()
        await interaction.response.edit_message(
            embed=self.paginator._build_embed(), view=self.paginator
        )


class UndoView(discord.ui.View):
    """A short-lived "Undo" button for reversible actions.

    ``undo_callback(interaction)`` performs the reversal and is responsible for
    responding to the interaction (e.g. ``edit_message``). Only the original
    requester may press it, and it can only fire once.
    """

    def __init__(self, undo_callback, *, requester_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.undo_callback = undo_callback
        self.requester_id = requester_id
        self._used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who ran this can undo it.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Undo", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def undo_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._used:
            return await interaction.response.send_message(
                embed=error_embed("Already undone", "This action was already reversed.", client=interaction.client),
                ephemeral=True,
            )
        self._used = True
        for c in self.children:
            if isinstance(c, discord.ui.Button):
                c.disabled = True
        try:
            await self.undo_callback(interaction)
        except Exception:
            logger.warning("[UndoView] undo callback failed", exc_info=True)
            await _interaction_followup_ephemeral(
                interaction, "Couldn't undo that — please redo it manually."
            )


class RetryView(discord.ui.View):
    """View with Retry button for flaky operations (e.g. API failures)."""

    def __init__(self, retry_callback, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.retry_callback = retry_callback

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        try:
            if self.message:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb and emb.footer and emb.footer.text:
                    emb.set_footer(text=emb.footer.text + " • ⏰ Expired")
                await self.message.edit(embed=emb, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Try again", style=discord.ButtonStyle.primary, emoji="🔄")
    async def retry_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        try:
            await self.retry_callback(interaction)
        except discord.NotFound:
            await _interaction_followup_ephemeral(
                interaction, "This message was deleted — run the command again."
            )
        except discord.Forbidden:
            logger.warning(
                "[RetryView] missing access editing message in channel=%s",
                getattr(interaction.channel, "id", None),
            )
            await _interaction_followup_ephemeral(
                interaction,
                "I can't update this message anymore (missing channel access). Run the command again.",
            )
            await _reenable_view_buttons(interaction, self)
        except discord.HTTPException as exc:
            logger.debug("[RetryView] refresh edit failed: %s", exc)
            await _interaction_followup_ephemeral(
                interaction, "Couldn't refresh — try again in a moment."
            )
            await _reenable_view_buttons(interaction, self)


class RefreshView(discord.ui.View):
    """View with Refresh button to invalidate cache and refetch (e.g. cycles, Baro)."""

    def __init__(self, refresh_callback, *, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.refresh_callback = refresh_callback

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        try:
            if self.message:
                emb = self.message.embeds[0] if self.message.embeds else None
                if emb and emb.footer and emb.footer.text:
                    emb.set_footer(text=emb.footer.text + " • ⏰ Expired")
                await self.message.edit(embed=emb, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Update data", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            await self.refresh_callback(interaction)
        except discord.NotFound:
            await _interaction_followup_ephemeral(
                interaction, "This message was deleted — run the command again."
            )
        except discord.Forbidden:
            logger.warning(
                "[RefreshView] missing access editing message in channel=%s",
                getattr(interaction.channel, "id", None),
            )
            await _interaction_followup_ephemeral(
                interaction,
                "I can't update this message anymore (missing channel access). Run the command again.",
            )
            await _reenable_view_buttons(interaction, self)
        except discord.HTTPException as exc:
            logger.debug("[RefreshView] refresh edit failed: %s", exc)
            await _interaction_followup_ephemeral(
                interaction, "Couldn't refresh — try again in a moment."
            )
            await _reenable_view_buttons(interaction, self)


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
            return await interaction.response.send_message(
                embed=error_embed("Channel not found", "That voice channel is gone.", client=interaction.client),
                ephemeral=True,
            )
        try:
            limit = int(self.values[0])
        except ValueError:
            return await interaction.response.send_message(
                embed=error_embed("Invalid limit", "Choose a limit between 0 and 99.", client=interaction.client),
                ephemeral=True,
            )

        await vc.edit(user_limit=limit, reason="VC limit")
        await interaction.response.send_message(
            embed=success_embed("Limit updated", "Squad capacity updated.", client=interaction.client),
            ephemeral=True,
        )
        try:
            from bot import update_vc_panel_embed
            await update_vc_panel_embed(interaction.guild, self.vc_id, force=True)
        except Exception:
            pass


class SetLimitView(discord.ui.View):
    def __init__(self, vc_id: int):
        super().__init__(timeout=120)
        self.vc_id = vc_id
        self.add_item(SetLimitSelect(vc_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not interaction.guild:
            return False
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, self.vc_id),
            )
            row = await cur.fetchone()
        owner_id = int(row[0]) if row else None
        return await can_manage_temp_vc(member, interaction.guild, owner_id=owner_id)


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
        # Privacy presets (QoL #17)
        self.add_item(discord.ui.Button(label="Public", style=discord.ButtonStyle.success, emoji="🌐", custom_id=f"vc:{vc_id}:privacy_public", row=2))
        self.add_item(discord.ui.Button(label="Friends", style=discord.ButtonStyle.primary, emoji="👥", custom_id=f"vc:{vc_id}:privacy_friends", row=2))
        self.add_item(discord.ui.Button(label="Private", style=discord.ButtonStyle.secondary, emoji="🔐", custom_id=f"vc:{vc_id}:privacy_private", row=2))
        # Capacity quick presets
        self.add_item(discord.ui.Button(label="Cap 2", style=discord.ButtonStyle.secondary, emoji="2️⃣", custom_id=f"vc:{vc_id}:cap_2", row=3))
        self.add_item(discord.ui.Button(label="Cap 4", style=discord.ButtonStyle.secondary, emoji="4️⃣", custom_id=f"vc:{vc_id}:cap_4", row=3))
        self.add_item(discord.ui.Button(label="Cap 8", style=discord.ButtonStyle.secondary, emoji="8️⃣", custom_id=f"vc:{vc_id}:cap_8", row=3))
        self.add_item(discord.ui.Button(label="No Cap", style=discord.ButtonStyle.secondary, emoji="♾️", custom_id=f"vc:{vc_id}:cap_0", row=3))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not interaction.guild:
            return False

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT owner_id FROM temp_vcs WHERE guild_id=? AND channel_id=?",
                (interaction.guild.id, self.vc_id),
            )
            row = await cur.fetchone()
        owner_id = int(row[0]) if row else None
        return await can_manage_temp_vc(member, interaction.guild, owner_id=owner_id)

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
        self.add_item(discord.ui.Button(label="Open Ticket", style=discord.ButtonStyle.secondary, emoji="🎫", custom_id=f"complaints:{case_id}:ticket"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        return isinstance(member, discord.Member) and is_mod(member)

    async def dm_user(
        self,
        guild: discord.Guild,
        user_id: int,
        status: str,
        bot,
        *,
        mod_name: Optional[str] = None,
        note: Optional[str] = None,
    ) -> bool:
        """Returns True if DM sent or not needed, False if user exists but DMs blocked."""
        from core.complaint_notify import send_complaint_status_dm

        return await send_complaint_status_dm(
            guild,
            user_id,
            self.case_id,
            status,
            bot,
            mod_name=mod_name,
            note=note,
        )

    async def set_status(
        self,
        interaction: discord.Interaction,
        status: str,
        *,
        bot,
        dm_override: bool = True,
        note: Optional[str] = None,
    ) -> Tuple[Optional[int], bool]:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM complaints WHERE guild_id=? AND case_id=?",
                (interaction.guild.id, self.case_id),
            )
            row = await cur.fetchone()
            if not row:
                return (None, True)
            user_id = int(row[0])

            await db.execute(
                "UPDATE complaints SET status=?, last_update_at=? WHERE guild_id=? AND case_id=?",
                (status, now_utc().isoformat(), interaction.guild.id, self.case_id),
            )
            await db.commit()

        dm_ok = True
        if dm_override:
            mod_name = interaction.user.display_name if isinstance(interaction.user, discord.Member) else None
            dm_ok = await self.dm_user(
                interaction.guild,
                user_id,
                status,
                bot,
                mod_name=mod_name,
                note=note,
            )

        await log_complaint_action(interaction.guild.id, self.case_id, interaction.user.id, f"STATUS:{status}", guild=interaction.guild, bot=bot)
        return (user_id, dm_ok)


class RSVPView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Going", style=discord.ButtonStyle.success, emoji="✅", custom_id="events:rsvp:going"))
        self.add_item(discord.ui.Button(label="Maybe", style=discord.ButtonStyle.primary, emoji="❔", custom_id="events:rsvp:maybe"))
        self.add_item(discord.ui.Button(label="Can't", style=discord.ButtonStyle.danger, emoji="❌", custom_id="events:rsvp:no"))
        self.add_item(discord.ui.Button(label="+15m late", style=discord.ButtonStyle.secondary, emoji="⏱️", custom_id="events:delay:15"))
        self.add_item(discord.ui.Button(label="Cancel event", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="events:cancel"))

    @staticmethod
    def format_rsvp_summary(counts: dict[str, int]) -> str:
        """RSVP counts with a proportional going/maybe/no bar."""
        going = int(counts.get("GOING", 0))
        maybe = int(counts.get("MAYBE", 0))
        no = int(counts.get("NO", 0))
        total = going + maybe + no
        if total <= 0:
            return "✅ 0 · ❔ 0 · ❌ 0\n▱▱▱▱▱▱▱▱▱▱▱▱"
        yes_pct = going / total * 100
        maybe_pct = maybe / total * 100
        no_pct = no / total * 100
        return (
            f"✅ **{going}** · ❔ **{maybe}** · ❌ **{no}**\n"
            f"Going {render_bar(yes_pct, length=8, show_pct=False)}  "
            f"Maybe {render_bar(maybe_pct, length=8, show_pct=False)}  "
            f"No {render_bar(no_pct, length=8, show_pct=False)}"
        )

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
        summary = self.format_rsvp_summary(counts)
        from core.embed_footers import footer_for
        embed.set_footer(text=f"{summary} · {footer_for('community_rsvp')}")
        # Replace or add RSVP field
        rsvp_field_idx = next((i for i, f in enumerate(embed.fields) if f.name == "RSVP"), None)
        if rsvp_field_idx is not None:
            embed.set_field_at(rsvp_field_idx, name="RSVP", value=summary, inline=False)
        else:
            embed.add_field(name="RSVP", value=summary, inline=False)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            embed=success_embed("RSVP recorded", "Your response was saved.", client=interaction.client),
            ephemeral=True,
        )

    async def delay_event(self, interaction: discord.Interaction, minutes: int = 15):
        if not interaction.guild:
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        msg_id = interaction.message.id
        guild_id = interaction.guild.id
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT creator_id, start_ts, end_ts FROM events WHERE guild_id=? AND message_id=?",
                (guild_id, msg_id),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message(
                embed=error_embed("Event not found", "This event may have ended or been removed.", client=interaction.client),
                ephemeral=True,
            )
        creator_id, start_ts, end_ts = int(row[0]), int(row[1]), int(row[2])
        from core.utils import is_mod

        if interaction.user.id != creator_id and not (
            isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        ):
            return await interaction.response.send_message(
                "Only the event creator or a moderator can delay this event.",
                ephemeral=True,
            )
        delta = minutes * 60
        new_start = start_ts + delta
        new_end = end_ts + delta
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE events SET start_ts=?, end_ts=? WHERE guild_id=? AND message_id=?",
                (new_start, new_end, guild_id, msg_id),
            )
            await db.commit()
        embed = interaction.message.embeds[0]
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT title, description FROM events WHERE guild_id=? AND message_id=?",
                (guild_id, msg_id),
            )
            ev = await cur.fetchone()
        briefing = ev[1] if ev and ev[1] else ""
        embed.description = (
            f"**When:** <t:{new_start}:F>  _( <t:{new_start}:R> )_\n\n"
            f"**Ends:** <t:{new_end}:t>\n\n"
            f"⏱️ _Delayed +{minutes}m by {interaction.user.display_name}_\n\n"
            f"**Briefing:**\n{briefing}"
        )
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"Event pushed back **{minutes} minutes**.", ephemeral=True
        )

    async def cancel_event(self, interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import deny_server_only
            return await deny_server_only(interaction)
        msg_id = interaction.message.id
        guild_id = interaction.guild.id
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT creator_id, title FROM events WHERE guild_id=? AND message_id=?",
                (guild_id, msg_id),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message(
                embed=error_embed("Event not found", "This event may have ended or been removed.", client=interaction.client),
                ephemeral=True,
            )
        creator_id, title = int(row[0]), row[1]
        from core.utils import is_mod

        if interaction.user.id != creator_id and not (
            isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        ):
            return await interaction.response.send_message(
                "Only the event creator or a moderator can cancel this event.",
                ephemeral=True,
            )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE events SET ended=1 WHERE guild_id=? AND message_id=?",
                (guild_id, msg_id),
            )
            await db.commit()
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title=title)
        embed.title = f"❌ Cancelled — {title}"
        embed.color = discord.Color.red()
        embed.description = (
            f"_Cancelled by {interaction.user.display_name}_\n\n"
            + (embed.description or "")
        )
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            embed=success_embed("Event cancelled", "The event was cancelled and RSVPs cleared.", client=interaction.client),
            ephemeral=True,
        )


class AutoModAppealView(discord.ui.View):
    """Short-lived button for users to flag an automod removal."""

    def __init__(
        self,
        *,
        guild_id: int,
        user_id: int,
        violation_type: str,
        preview: str,
        log_channel_id: int | None,
    ):
        super().__init__(timeout=3600)
        self.guild_id = guild_id
        self.user_id = user_id
        self.violation_type = violation_type
        self.preview = preview[:300]
        self.log_channel_id = log_channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                embed=error_embed("Not for you", "This appeal is not for you.", client=interaction.client),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Report false positive", emoji="🚩", style=discord.ButtonStyle.secondary)
    async def report_fp(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        guild = interaction.client.get_guild(self.guild_id)
        sent = False
        if guild and self.log_channel_id:
            ch = guild.get_channel(self.log_channel_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        embed=obsidian_embed(
                            "🚩 Automod false-positive report",
                            f"**User:** <@{self.user_id}> ({self.user_id})\n"
                            f"**Violation type:** {self.violation_type}\n"
                            f"**Message preview:** {self.preview}",
                            color=discord.Color.orange(),
                            client=interaction.client,
                        )
                    )
                    sent = True
                except Exception:
                    pass
        await interaction.response.edit_message(view=self)
        note = "Mods have been notified." if sent else "Couldn't reach the mod log channel — tell staff manually."
        await interaction.followup.send(f"Thanks — {note}", ephemeral=True)


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
            return await interaction.response.send_message(
                embed=error_embed("Owners only", "Only the listing owner can mark it as sold.", client=interaction.client),
                ephemeral=True,
            )
        
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
            return await interaction.response.send_message(
                embed=error_embed("Owners only", "Only the listing owner can delete it.", client=interaction.client),
                ephemeral=True,
            )
        
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
    """View for giveaway enter/leave/participants buttons. All buttons use giveaway_id in custom_id so multiple giveaways work."""
    def __init__(self, giveaway_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        if giveaway_id is None:
            return
        # All buttons must have unique custom_id per giveaway so persistent views route to the correct giveaway
        enter_btn = discord.ui.Button(
            label="Enter Giveaway",
            style=discord.ButtonStyle.green,
            emoji="🎉",
            custom_id=f"giveaway:{giveaway_id}:enter",
        )
        enter_btn.callback = self.enter_giveaway
        self.add_item(enter_btn)
        leave_btn = discord.ui.Button(
            label="Leave Giveaway",
            style=discord.ButtonStyle.red,
            emoji="❌",
            custom_id=f"giveaway:{giveaway_id}:leave",
        )
        leave_btn.callback = self.leave_giveaway
        self.add_item(leave_btn)
        participants_btn = discord.ui.Button(
            label="View Participants",
            style=discord.ButtonStyle.secondary,
            emoji="👥",
            custom_id=f"giveaway:{giveaway_id}:participants",
        )
        participants_btn.callback = self.view_participants
        self.add_item(participants_btn)

    async def enter_giveaway(self, interaction: discord.Interaction):
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
        
        failures: list[str] = []
        if ended:
            failures.append("This giveaway has already ended.")
        if end_time_str:
            try:
                from datetime import datetime, timezone as _tz
                end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=_tz.utc)
                if end_dt <= now_utc():
                    failures.append(f"Giveaway ended <t:{int(end_dt.timestamp())}:R>.")
            except Exception:
                pass
        
        if required_role_id:
            role = interaction.guild.get_role(required_role_id)
            if role and role not in interaction.user.roles:
                failures.append(f"Missing role: {role.mention}")
            elif role is None:
                failures.append("Required role is no longer available on this server.")
        
        if min_level:
            from database import get_user_xp
            _, user_level, _ = await get_user_xp(interaction.guild.id, interaction.user.id)
            if user_level < min_level:
                failures.append(f"Need level **{min_level}** (you're **{user_level}**).")
        
        if failures:
            body = "**You can't enter yet:**\n" + "\n".join(f"• {line}" for line in failures)
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Entry Requirements Not Met",
                    body,
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
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
        
        # Parse end time for the confirmation embed
        try:
            from datetime import datetime, timezone as _tz
            end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
            end_ts = int(end_dt.timestamp())
            end_str = f"<t:{end_ts}:R> (<t:{end_ts}:F>)"
        except Exception:
            end_str = "soon"

        # Respond to the interaction first — prevents the 3-second timeout while editing
        await interaction.response.send_message(
            f"You're in — **{entry_count}** entr{'y' if entry_count == 1 else 'ies'}",
            ephemeral=True,
        )

        # Update the public embed entry count in the background (non-blocking)
        try:
            message = interaction.message
            if message:
                await _update_giveaway_entry_embed(message, entry_count)
        except Exception as e:
            logger.debug(f"Could not update giveaway embed: {e}")

    async def leave_giveaway(self, interaction: discord.Interaction):
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
            if message:
                await _update_giveaway_entry_embed(message, entry_count)
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

    async def view_participants(self, interaction: discord.Interaction):
        """Show who entered the giveaway (ephemeral)."""
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
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT prize, ended FROM giveaways WHERE id = ?
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
            prize, ended = row
            cur = await db.execute("""
                SELECT user_id, entered_at FROM giveaway_entries WHERE giveaway_id = ? ORDER BY entered_at ASC
            """, (self.giveaway_id,))
            entries = await cur.fetchall()
        total = len(entries)
        max_show = 25
        lines = []
        for (user_id, entered_at) in entries[:max_show]:
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            lines.append(f"• {name}")
        if total == 0:
            body = "No participants yet."
        else:
            body = "\n".join(lines)
            if total > max_show:
                body += f"\n\n_... and {total - max_show} more_"
        await interaction.response.send_message(
            embed=obsidian_embed(
                f"👥 Participants — {prize}",
                body,
                color=discord.Color.blue(),
                footer=f"{total} entr{'y' if total == 1 else 'ies'} total" + (" • Ended" if ended else ""),
                client=interaction.client,
            ),
            ephemeral=True
        )


class ApplicationManageView(discord.ui.View):
    """View for moderators to manage applications — pipeline stages + approve/reject."""
    def __init__(self, application_id: int):
        super().__init__(timeout=None)
        self.application_id = application_id

        for label, stage, style in (
            ("Interview", "interview", discord.ButtonStyle.primary),
            ("Trial", "trial", discord.ButtonStyle.primary),
            ("Accept", "accepted", discord.ButtonStyle.success),
        ):
            btn = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"application:{application_id}:stage:{stage}",
            )
            btn.callback = self._make_stage_cb(stage, label)
            self.add_item(btn)

        approve_button = discord.ui.Button(label="Approve", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"application:{application_id}:approve")
        approve_button.callback = self.approve_button
        self.add_item(approve_button)

        reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id=f"application:{application_id}:reject")
        reject_button.callback = self.reject_button
        self.add_item(reject_button)

    def _make_stage_cb(self, stage: str, label: str):
        async def _cb(interaction: discord.Interaction):
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                from core.reply_helpers import deny_mods_only
                return await deny_mods_only(interaction)
            await interaction.response.defer(ephemeral=True)
            status_map = {
                "interview": "INTERVIEW",
                "trial": "TRIAL",
                "accepted": "ACCEPTED",
            }
            new_status = status_map.get(stage, "PENDING")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE applications SET pipeline_stage=?, status=? WHERE id=?",
                    (stage, new_status if new_status != "ACCEPTED" else "PENDING", self.application_id),
                )
                await db.commit()
            embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            if embed:
                for i, field in enumerate(embed.fields):
                    if field.name == "Status":
                        embed.set_field_at(i, name="Status", value=f"📋 {label}", inline=True)
                        break
                else:
                    embed.add_field(name="Pipeline", value=label, inline=True)
                await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(f"Stage set to **{label}**.", ephemeral=True)
        return _cb
    
    async def approve_button(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import deny_mods_only
            return await deny_mods_only(interaction)
        
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
        applicant_dm_ok = True  # no DM needed if no member
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

                applicant_dm_ok = False
                try:
                    message_text = f"Congratulations! Your application to join {interaction.guild.name} has been approved."
                    if role_assigned:
                        message_text += "\n\nYou have been assigned the **Oathtaker** role!"

                    await user.send(
                        embed=obsidian_embed(
                            "Application approved",
                            message_text,
                            color=discord.Color.green(),
                            client=interaction.client,
                        )
                    )
                    applicant_dm_ok = True
                except discord.Forbidden:
                    pass

        mod_msg = "Application approved."
        if user_id and not applicant_dm_ok:
            mod_msg += " **Couldn't DM the applicant** — ask them to enable DMs from this server or tell them in-channel."
        await interaction.followup.send(mod_msg, ephemeral=True)
    
    async def reject_button(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            from core.reply_helpers import deny_mods_only
            return await deny_mods_only(interaction)
        
        # Show modal for rejection reason
        from core.modals import ApplicationRejectModal
        modal = ApplicationRejectModal(self.application_id)
        await interaction.response.send_modal(modal)


class ApplicationPanelView(discord.ui.View):
    """View with button to start an application."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        
        # Add button with custom_id for persistence
        apply_button = discord.ui.Button(
            label="Start application (uses DMs)",
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

        try:
            from commands.applications.application import start_application_process
            await start_application_process(interaction)
        except Exception as e:
            # Log so it appears in Railway; view callbacks are not routed through on_interaction
            logger.error(
                "[ApplicationPanelView] Application button failed: %s",
                e,
                exc_info=True,
                extra={"guild_id": getattr(interaction.guild, "id", None), "user_id": getattr(interaction.user, "id", None)},
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Couldn't start the application right now. Try again in a moment or ping a moderator if it keeps happening. _(Only you see this.)_",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "Couldn't start the application right now. Try again in a moment or ping a moderator if it keeps happening. _(Only you see this.)_",
                        ephemeral=True,
                    )
            except (discord.errors.NotFound, discord.errors.InteractionResponded, discord.errors.HTTPException):
                pass
