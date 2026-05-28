"""Ticket system commands."""
import discord
from discord import app_commands
from typing import Optional
from datetime import datetime, timezone
import asyncio
import re
import io

from core.utils import obsidian_embed, success_embed, is_mod, format_timestamp_readable, EMBED_COLORS
from database import DB_PATH, now_utc, get_guild_setting
from views import ConfirmView
import aiosqlite


def generate_ticket_id(username: str, subject: str) -> str:
    """Generate a ticket ID based on username and subject."""
    # Clean username: remove special characters, spaces, make lowercase
    clean_username = re.sub(r'[^a-zA-Z0-9]', '', username.lower())[:15]  # Max 15 chars
    
    # Clean subject: remove special characters except hyphens, spaces become hyphens, make lowercase
    clean_subject = re.sub(r'[^a-zA-Z0-9\s-]', '', subject.lower())
    clean_subject = re.sub(r'\s+', '-', clean_subject)  # Replace spaces with hyphens
    clean_subject = clean_subject[:30]  # Max 30 chars
    
    # Format: username-subject
    ticket_id = f"{clean_username}-{clean_subject}"
    
    # Ensure it's not too long (Discord channel names have limits)
    if len(ticket_id) > 50:
        # Truncate subject if needed
        max_subject_len = 50 - len(clean_username) - 1  # -1 for hyphen
        clean_subject = clean_subject[:max_subject_len]
        ticket_id = f"{clean_username}-{clean_subject}"
    
    return ticket_id


async def _get_ticket_row_by_channel(guild_id: int, channel_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        return await cur.fetchone()


async def _get_ticket_row_by_id(ticket_db_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tickets WHERE id=?", (ticket_db_id,))
        return await cur.fetchone()


def _format_dt_iso(iso_str: Optional[str]) -> str:
    """Format ISO datetime as readable Discord timestamp (full date + relative)."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return format_timestamp_readable(dt)
    except Exception:
        return iso_str


async def _build_transcript(channel: discord.TextChannel, limit: int = 1000) -> bytes:
    """Build a simple plaintext transcript."""
    lines: list[str] = []
    lines.append(f"Transcript for #{channel.name} ({channel.id})")
    lines.append(f"Generated at: {now_utc().isoformat()}")
    lines.append("")

    try:
        async for msg in channel.history(limit=limit, oldest_first=True):
            ts = int(msg.created_at.replace(tzinfo=timezone.utc).timestamp())
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content or ""
            if msg.attachments:
                att = " ".join(a.url for a in msg.attachments)
                content = f"{content}\n[attachments] {att}".strip()
            if msg.embeds:
                content = f"{content}\n[embeds] {len(msg.embeds)} embed(s)".strip()
            lines.append(f"[{ts}] {author}: {content}".rstrip())
    except Exception as e:
        lines.append("")
        lines.append(f"[error] Failed to fetch full history: {e}")

    return ("\n".join(lines)).encode("utf-8", errors="replace")


async def _send_transcript_to_log(
    guild: discord.Guild,
    ticket_row: aiosqlite.Row,
    transcript_bytes: bytes,
    file_name: str,
) -> tuple[Optional[int], Optional[int]]:
    """Send transcript file to configured ticket transcript log channel (if any)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id FROM log_channels WHERE guild_id=? AND log_type='ticket_transcript' AND enabled=1",
            (guild.id,),
        )
        row = await cur.fetchone()

    if not row or not row[0]:
        return None, None

    log_channel = guild.get_channel(int(row[0]))
    if not isinstance(log_channel, discord.TextChannel):
        return None, None

    f = discord.File(fp=io.BytesIO(transcript_bytes), filename=file_name)
    try:
        priority_str = f"\n**Priority:** {(ticket_row['priority'] or 'normal').capitalize()}"
    except (KeyError, IndexError, TypeError):
        priority_str = ""
    embed = obsidian_embed(
        "🧾 Ticket Transcript",
        f"**Ticket:** `{ticket_row['ticket_id']}`\n"
        f"**Subject:** {ticket_row['subject']}\n"
        f"**User:** <@{ticket_row['user_id']}>\n"
        f"**Channel:** <#{ticket_row['channel_id']}>\n"
        f"**Created:** {_format_dt_iso(ticket_row['created_at'])}\n"
        f"**Closed:** {_format_dt_iso(ticket_row['closed_at'])}{priority_str}",
        color=discord.Color.dark_grey(),
        client=None,
    )
    msg = await log_channel.send(embed=embed, file=f)
    return log_channel.id, msg.id


class TicketNoteModal(discord.ui.Modal, title="Add internal ticket note"):
    note = discord.ui.TextInput(
        label="Note (internal)",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    def __init__(self, ticket_db_id: int):
        super().__init__()
        self.ticket_db_id = ticket_db_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO ticket_notes (guild_id, ticket_id, author_id, note, created_at) VALUES (?,?,?,?,?)",
                (interaction.guild.id, self.ticket_db_id, interaction.user.id, str(self.note), now_utc().isoformat()),
            )
            await db.commit()

        await interaction.followup.send("Note saved.", ephemeral=True)


class TicketCloseModal(discord.ui.Modal, title="Close ticket"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
        placeholder="Optional reason for closing this ticket.",
    )

    def __init__(self, ticket_db_id: int):
        super().__init__()
        self.ticket_db_id = ticket_db_id

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await close_ticket(
            interaction=interaction,
            ticket_db_id=self.ticket_db_id,
            closer_id=interaction.user.id,
            reason=str(self.reason).strip() or None,
        )


class TicketSatisfactionView(discord.ui.View):
    def __init__(self, ticket_db_id: int):
        super().__init__(timeout=60 * 60 * 24 * 3)  # 3 days
        self.ticket_db_id = ticket_db_id

        for rating in range(1, 6):
            btn = discord.ui.Button(
                label=str(rating),
                style=discord.ButtonStyle.secondary if rating < 4 else discord.ButtonStyle.success,
                custom_id=f"ticket:rate:{ticket_db_id}:{rating}",
            )
            btn.callback = self._rate  # type: ignore
            self.add_item(btn)

    async def _rate(self, interaction: discord.Interaction):
        # Works in DMs too
        cid = interaction.data.get("custom_id") if interaction.data else ""
        parts = cid.split(":")
        if len(parts) != 4:
            return await interaction.response.send_message("Invalid rating.", ephemeral=True)

        ticket_db_id = int(parts[2])
        rating = int(parts[3])

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE tickets SET satisfaction_rating=? WHERE id=?",
                (rating, ticket_db_id),
            )
            await db.commit()

        for item in self.children:
            item.disabled = True  # type: ignore
        try:
            await interaction.response.edit_message(
                embed=obsidian_embed("✅ Thanks!", f"Saved rating: **{rating}/5**.", color=discord.Color.green()),
                view=self,
            )
        except Exception:
            # fallback
            await interaction.response.send_message("Thanks! Rating saved.", ephemeral=True)


class TicketControlView(discord.ui.View):
    """Persistent control panel for a ticket."""

    def __init__(self, ticket_db_id: int, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_db_id = ticket_db_id
        self.ticket_id = ticket_id

        claim_btn = discord.ui.Button(
            label="Claim",
            style=discord.ButtonStyle.primary,
            emoji="🫡",
            custom_id=f"ticket:claim:{ticket_db_id}",
        )
        claim_btn.callback = self._claim  # type: ignore
        self.add_item(claim_btn)

        note_btn = discord.ui.Button(
            label="Add Note",
            style=discord.ButtonStyle.secondary,
            emoji="📝",
            custom_id=f"ticket:note:{ticket_db_id}",
        )
        note_btn.callback = self._note  # type: ignore
        self.add_item(note_btn)

        transcript_btn = discord.ui.Button(
            label="Transcript",
            style=discord.ButtonStyle.secondary,
            emoji="🧾",
            custom_id=f"ticket:transcript:{ticket_db_id}",
        )
        transcript_btn.callback = self._transcript  # type: ignore
        self.add_item(transcript_btn)

        escalate_btn = discord.ui.Button(
            label="Escalate",
            style=discord.ButtonStyle.danger,
            emoji="🔴",
            custom_id=f"ticket:escalate:{ticket_db_id}",
        )
        escalate_btn.callback = self._escalate  # type: ignore
        self.add_item(escalate_btn)

        close_btn = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.danger,
            emoji="🔒",
            custom_id=f"ticket:close:{ticket_db_id}",
        )
        close_btn.callback = self._close  # type: ignore
        self.add_item(close_btn)

    async def _claim(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            # Set assigned_to and claimed_at; also set first_response_at if missing
            cur = await db.execute(
                "SELECT assigned_to, claimed_at, first_response_at FROM tickets WHERE id=?",
                (self.ticket_db_id,),
            )
            row = await cur.fetchone()
            now_iso = now_utc().isoformat()
            if row:
                assigned_to, claimed_at, first_response_at = row
                if assigned_to and int(assigned_to) != interaction.user.id:
                    return await interaction.followup.send(
                        f"This ticket is already claimed by <@{assigned_to}>.",
                        ephemeral=True,
                    )

            await db.execute(
                "UPDATE tickets SET assigned_to=?, claimed_at=COALESCE(claimed_at, ?), first_response_at=COALESCE(first_response_at, ?), last_activity_at=? WHERE id=?",
                (interaction.user.id, now_iso, now_iso, now_iso, self.ticket_db_id),
            )
            await db.commit()

        await interaction.followup.send(f"Claimed by {interaction.user.mention}.", ephemeral=True)

    async def _note(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        await interaction.response.send_modal(TicketNoteModal(self.ticket_db_id))

    async def _transcript(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        ticket_row = await _get_ticket_row_by_id(self.ticket_db_id)
        if not ticket_row:
            return await interaction.followup.send("Ticket not found.", ephemeral=True)

        channel = interaction.guild.get_channel(int(ticket_row["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send("Ticket channel not found.", ephemeral=True)

        data = await _build_transcript(channel)
        file_name = f"ticket-{ticket_row['ticket_id']}.txt"

        log_channel_id, log_message_id = await _send_transcript_to_log(
            interaction.guild, ticket_row, data, file_name
        )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE tickets SET transcript_channel_id=?, transcript_message_id=? WHERE id=?",
                (log_channel_id, log_message_id, self.ticket_db_id),
            )
            await db.commit()

        await interaction.followup.send("Transcript generated.", ephemeral=True)

    async def _escalate(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT escalated FROM tickets WHERE id=?",
                (self.ticket_db_id,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return await interaction.followup.send("This ticket is already escalated.", ephemeral=True)

            now_iso = now_utc().isoformat()
            await db.execute(
                "UPDATE tickets SET escalated=1, escalated_at=?, escalated_by=?, last_activity_at=? WHERE id=?",
                (now_iso, interaction.user.id, now_iso, self.ticket_db_id),
            )
            await db.commit()

        ticket_row = await _get_ticket_row_by_id(self.ticket_db_id)
        channel = interaction.guild.get_channel(int(ticket_row["channel_id"])) if ticket_row else None

        role_id_str = await get_guild_setting(interaction.guild.id, "ticket_escalation_role_id")
        ping_content = None
        if role_id_str:
            try:
                role = interaction.guild.get_role(int(role_id_str))
                if role:
                    ping_content = f"{role.mention} — **Ticket escalated** by {interaction.user.mention}"
            except (ValueError, TypeError):
                pass

        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    content=ping_content or f"🔴 **Ticket escalated** by {interaction.user.mention}",
                    embed=obsidian_embed(
                        "🔴 Escalated",
                        "This ticket has been marked as escalated and requires senior staff attention.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                )
            except discord.Forbidden:
                pass

        await interaction.followup.send("Ticket escalated.", ephemeral=True)

    async def _close(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        await interaction.response.send_modal(TicketCloseModal(self.ticket_db_id))


async def close_ticket(
    interaction: discord.Interaction,
    ticket_db_id: int,
    closer_id: int,
    reason: Optional[str] = None,
):
    """Close ticket: update DB, generate transcript, DM satisfaction, delete channel."""
    if not interaction.guild:
        try:
            await interaction.followup.send(
                "Could not close ticket (no server context). Try again from the ticket channel.",
                ephemeral=True,
            )
        except Exception:
            pass
        return

    ticket_row = await _get_ticket_row_by_id(ticket_db_id)
    if not ticket_row:
        return await interaction.followup.send("Ticket not found.", ephemeral=True)

    channel = interaction.guild.get_channel(int(ticket_row["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return await interaction.followup.send("Ticket channel not found.", ephemeral=True)

    now_iso = now_utc().isoformat()

    # Generate transcript first
    transcript_bytes = await _build_transcript(channel)
    file_name = f"ticket-{ticket_row['ticket_id']}.txt"
    log_channel_id, log_message_id = await _send_transcript_to_log(
        interaction.guild, ticket_row, transcript_bytes, file_name
    )

    # Update DB
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET status='closed', closed_at=?, closed_by=?, transcript_channel_id=?, transcript_message_id=? WHERE id=?",
            (now_iso, closer_id, log_channel_id, log_message_id, ticket_db_id),
        )
        await db.commit()

    try:
        from core.audit import log_audit
        bot_ref = getattr(interaction.client, "bot", interaction.client) or interaction.client
        await log_audit(interaction.guild.id, "ticket_close", closer_id, target_id=int(ticket_row["user_id"]), target_type="user",
            details=f"Ticket {ticket_row['ticket_id']}: {reason or 'No reason'}", bot=bot_ref)
    except Exception:
        pass

    # Notify in channel
    close_embed = obsidian_embed(
        f"Ticket `{ticket_row['ticket_id']}` Closed",
        f"**Closed by:** <@{closer_id}>\n"
        f"**Reason:** {reason or 'No reason provided'}\n\n"
        "This channel will be archived in 10 seconds.",
        color=discord.Color.orange(),
        client=interaction.client,
    )
    try:
        await channel.send(embed=close_embed)
    except Exception:
        pass

    # DM satisfaction request
    try:
        user = interaction.guild.get_member(int(ticket_row["user_id"])) or await interaction.client.fetch_user(int(ticket_row["user_id"]))  # type: ignore
        if user:
            dm_embed = obsidian_embed(
                "📝 Ticket feedback",
                f"How was the help you received for **{ticket_row['subject']}**?\n"
                "Tap a rating below (1 = poor, 5 = great).",
                color=discord.Color.blurple(),
                client=interaction.client,
            )
            await user.send(embed=dm_embed, view=TicketSatisfactionView(ticket_db_id))
    except Exception:
        pass

    # Delete channel after delay
    await asyncio.sleep(10)
    try:
        await channel.delete(reason=f"Ticket closed by {closer_id}")
    except discord.Forbidden:
        pass


async def create_ticket_for_user(interaction: discord.Interaction, target_member: discord.Member, subject: str):
    """Create a ticket for another user (mod action)."""
    from core.utils import obsidian_embed, EMBED_COLORS
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.followup.send("Invalid context.", ephemeral=True)
    username = target_member.display_name or target_member.name
    ticket_id = generate_ticket_id(username, subject)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
        counter = 1
        original_ticket_id = ticket_id
        while await cur.fetchone():
            ticket_id = f"{original_ticket_id}-{counter}"
            if len(ticket_id) > 50:
                max_base_len = 50 - len(str(counter)) - 1
                ticket_id = f"{original_ticket_id[:max_base_len]}-{counter}"
            cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
            counter += 1
    channel = await create_ticket_channel(interaction.guild, target_member, ticket_id, subject)
    if not channel:
        return await interaction.followup.send(
            embed=obsidian_embed("❌ Permission Error", "I don't have permission to create channels.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tickets (guild_id, user_id, channel_id, ticket_id, subject, status, created_at, last_activity_at, tag, priority)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
        """, (interaction.guild.id, target_member.id, channel.id, ticket_id, subject, now_utc().isoformat(), now_utc().isoformat(), None, "normal"))
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        ticket_db_id = (await cur.fetchone())[0]
    fields = [("Subject", subject, True), ("Status", "Open", True), ("Created For", target_member.mention, True), ("Created By", interaction.user.mention, True)]
    embed = obsidian_embed(
        f"Ticket #{ticket_id}",
        f"Ticket created for {target_member.mention} by {interaction.user.mention}.\n\nStaff will respond shortly.",
        color=EMBED_COLORS["success"], fields=fields, author=interaction.user,
        thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
        footer=f"Ticket ID: {ticket_id}", client=interaction.client,
    )
    await channel.send(embed=embed)
    controls = TicketControlView(int(ticket_db_id), ticket_id)
    ctrl_msg = await channel.send(embed=obsidian_embed("🎫 Ticket Controls", "Staff controls: claim, add note, transcript, close.", color=discord.Color.blurple(), client=interaction.client), view=controls)
    bot_ref = getattr(interaction.client, "bot", interaction.client) or interaction.client
    if hasattr(bot_ref, "add_view"):
        bot_ref.add_view(controls, message_id=ctrl_msg.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET control_message_id=? WHERE id=?", (ctrl_msg.id, ticket_db_id))
        await db.commit()
    await channel.send(f"{target_member.mention}, a ticket has been created for you.")
    await interaction.followup.send(embed=obsidian_embed("✅ Ticket Created", f"Ticket for {target_member.mention}: {channel.mention}", color=EMBED_COLORS["success"], client=interaction.client), ephemeral=True)


async def create_ticket_channel(guild: discord.Guild, user: discord.Member, ticket_id: str, subject: str) -> Optional[discord.TextChannel]:
    """Create a ticket channel for a user."""
    # Get or create ticket category
    category_name = "Tickets"
    category = discord.utils.get(guild.categories, name=category_name)
    
    if not category:
        try:
            category = await guild.create_category(category_name)
        except discord.Forbidden:
            return None
    
    # Create channel - use ticket_id directly (already formatted)
    channel_name = ticket_id.lower()
    
    # Ensure channel name meets Discord requirements (lowercase, no spaces, max 100 chars)
    channel_name = channel_name.replace(' ', '-').lower()[:100]
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        }
        
        # Add mods
        for member in guild.members:
            if is_mod(member):
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket created by {user.display_name}"
        )
        return channel
    except discord.Forbidden:
        return None


def setup(bot, group=None):
    """Register ticket commands."""

    my_tickets_decorator = group.command(name="my_tickets", description="List your open tickets.") if group else None
    if my_tickets_decorator:
        @my_tickets_decorator
        async def my_tickets(interaction: discord.Interaction):
            """List user's open tickets."""
            if not interaction.guild:
                return await interaction.response.send_message("Use in a server.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT ticket_id, subject, status, channel_id, created_at FROM tickets WHERE guild_id=? AND user_id=? AND status='open' ORDER BY created_at DESC LIMIT 10",
                    (interaction.guild.id, interaction.user.id),
                )
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed("📋 No Open Tickets", "You have no open tickets. Use **`/ticket`** to create one.", color=discord.Color.blue(), client=interaction.client),
                    ephemeral=True,
                )
            lines = []
            for tid, subject, status, ch_id, created in rows:
                ch = interaction.guild.get_channel(ch_id)
                jump = f" [Jump](https://discord.com/channels/{interaction.guild.id}/{ch_id})" if ch else ""
                lines.append(f"**{tid}** — {subject[:40]}{'…' if len(subject) > 40 else ''}{jump}")
            await interaction.followup.send(
                embed=obsidian_embed("📋 Your Open Tickets", "\n".join(lines), color=discord.Color.blue(), footer="Click Jump to open the ticket", client=interaction.client),
                ephemeral=True,
            )

    command_decorator = group.command(name="ticket", description="Open a support ticket — roles, bugs, questions, staff help.") if group else bot.tree.command(name="ticket", description="Open a support ticket.")
    
    @command_decorator
    @app_commands.describe(
        subject="Subject of your ticket",
        tag="Category/tag for the ticket (optional)",
        priority="Priority level (optional)"
    )
    @app_commands.choices(tag=[
        app_commands.Choice(name="General", value="General"),
        app_commands.Choice(name="Bug Report", value="Bug Report"),
        app_commands.Choice(name="Question", value="Question"),
        app_commands.Choice(name="Other", value="Other"),
    ])
    @app_commands.choices(priority=[
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="Urgent", value="urgent"),
    ])
    async def ticket(interaction: discord.Interaction, subject: str, tag: app_commands.Choice[str] = None, priority: app_commands.Choice[str] = None):
        """Create a support ticket."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        if not isinstance(interaction.user, discord.Member):
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Error",
                    "Could not create ticket.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Generate ticket ID based on username and subject
        username = interaction.user.display_name or interaction.user.name
        ticket_id = generate_ticket_id(username, subject)
        
        # Check if ticket ID already exists, append number if needed
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
            counter = 1
            original_ticket_id = ticket_id
            while await cur.fetchone():
                # Append counter to make it unique
                ticket_id = f"{original_ticket_id}-{counter}"
                # Ensure it doesn't exceed Discord's channel name limit (100 chars)
                if len(ticket_id) > 50:
                    # Truncate original and add counter
                    max_base_len = 50 - len(str(counter)) - 1  # -1 for hyphen
                    ticket_id = f"{original_ticket_id[:max_base_len]}-{counter}"
                cur = await db.execute("SELECT 1 FROM tickets WHERE guild_id=? AND ticket_id=?", (interaction.guild.id, ticket_id))
                counter += 1
        
        # Create ticket channel
        channel = await create_ticket_channel(interaction.guild, interaction.user, ticket_id, subject)
        
        if not channel:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Error",
                    "I don't have permission to create channels. Please contact an administrator.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        tag_val = tag.value if tag else None
        priority_val = (priority.value if priority else "normal").lower()
        # Store ticket in database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO tickets (guild_id, user_id, channel_id, ticket_id, subject, status, created_at, last_activity_at, tag, priority)
                VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, channel.id, ticket_id, subject, now_utc().isoformat(), now_utc().isoformat(), tag_val, priority_val))
            await db.commit()

            try:
                from database import check_and_unlock_achievement
                await check_and_unlock_achievement(interaction.guild.id, interaction.user.id, "ticket_creator", getattr(interaction.client, "bot", interaction.client), interaction=interaction)
            except Exception:
                pass

            cur = await db.execute("SELECT last_insert_rowid()")
            ticket_db_id = (await cur.fetchone())[0]
        
        # Send welcome message in ticket channel
        fields = [
            ("Subject", subject, True),
            ("Status", "Open", True),
            ("Priority", priority_val.capitalize(), True),
            ("Created By", interaction.user.mention, True),
        ]
        if tag_val:
            fields.insert(1, ("Tag", tag_val, True))
        embed = obsidian_embed(
            f"Ticket #{ticket_id}",
            "Staff will respond shortly. Use `/ticket close` to close this ticket.",
            color=discord.Color.green(),
            fields=fields,
            author=interaction.user,
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"Ticket ID: {ticket_id}",
            client=interaction.client,
        )
        await channel.send(embed=embed)

        # Ticket control panel (persistent view)
        controls = TicketControlView(int(ticket_db_id), ticket_id)
        ctrl_msg = await channel.send(
            embed=obsidian_embed(
                "🎫 Ticket Controls",
                "Staff controls: claim, add internal note, generate transcript, close.\n"
                "(*Buttons are for moderators.*)",
                color=discord.Color.blurple(),
                client=interaction.client,
            ),
            view=controls,
        )
        bot.add_view(controls, message_id=ctrl_msg.id)  # persist for this message

        # Store control message id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE tickets SET control_message_id=? WHERE id=?",
                (ctrl_msg.id, ticket_db_id),
            )
            await db.commit()

        await channel.send(f"{interaction.user.mention}, your ticket has been created!")

        # Auto-assign: ping a random online mod via DM
        try:
            from core.utils import get_mod_role
            mod_role = get_mod_role(interaction.guild)
            if mod_role:
                online_mods = [
                    m for m in mod_role.members
                    if not m.bot and m.status != discord.Status.offline and m.id != interaction.user.id
                ]
                if online_mods:
                    import random as _random
                    assigned_mod = _random.choice(online_mods)
                    priority_str = priority_val.capitalize() if priority_val else "Normal"
                    tag_str = f" [{tag_val}]" if tag_val else ""
                    try:
                        dm_embed = obsidian_embed(
                            "🎫 New Ticket Assigned",
                            f"> **{subject}**\n"
                            f"A new ticket has been opened in **{interaction.guild.name}** and auto-assigned to you.",
                            category="moderation",
                            fields=[
                                ("🆔 Ticket", f"`{ticket_id}`{tag_str}", True),
                                ("👤 Opened by", interaction.user.mention, True),
                                ("⚡ Priority", priority_str, True),
                                ("📌 Channel", channel.mention, False),
                            ],
                            footer="You can claim it officially with the Claim button in the ticket channel.",
                            client=interaction.client,
                        )
                        await assigned_mod.send(embed=dm_embed)
                        # Pre-assign in DB so the claim button shows the right owner
                        async with aiosqlite.connect(DB_PATH) as _db:
                            await _db.execute(
                                "UPDATE tickets SET assigned_to=? WHERE id=?",
                                (assigned_mod.id, ticket_db_id),
                            )
                            await _db.commit()
                        await channel.send(
                            f"📋 This ticket has been auto-assigned to {assigned_mod.mention}.",
                            allowed_mentions=discord.AllowedMentions(users=True),
                        )
                    except discord.Forbidden:
                        pass  # mod has DMs closed
        except Exception:
            pass  # never block ticket creation for notification errors

        embed = success_embed(
            "Ticket Created",
            f"Your ticket has been created: {channel.mention}\n**Ticket ID:** `{ticket_id}`",
            flair="Use `/community ticket message` in the channel to add info, `/community ticket close` when done.",
            client=interaction.client,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"Ticket ID: {ticket_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    command_decorator = group.command(name="ticket_close", description="Close a support ticket (moderators only).") if group else bot.tree.command(name="ticket_close", description="Close a support ticket (moderators only).")
    
    @command_decorator
    @app_commands.describe(reason="Reason for closing the ticket")
    async def ticket_close(interaction: discord.Interaction, reason: Optional[str] = None):
        """Close a support ticket."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Channel",
                    "This command can only be used in a ticket channel.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        # Find ticket
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, ticket_id, user_id, status FROM tickets
                WHERE guild_id=? AND channel_id=?
            """, (interaction.guild.id, interaction.channel.id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Not a Ticket",
                        "This channel is not a ticket channel.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    )
                )
            
            ticket_db_id, ticket_id, user_id, status = row
            
            if status == 'closed':
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Closed",
                        "This ticket is already closed.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    )
                )

        embed = obsidian_embed(
            "⚠️ Confirm Close",
            f"Close ticket `{ticket_id}`? A transcript will be saved and the channel will be archived.",
            color=discord.Color.orange(),
            client=interaction.client,
        )
        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if not confirmed:
                await btn_interaction.followup.send("Cancelled.", ephemeral=True)
                return
            if btn_interaction.user.id != interaction.user.id:
                await btn_interaction.followup.send("Only the person who started this can confirm.", ephemeral=True)
                return
            await close_ticket(
                interaction=btn_interaction,
                ticket_db_id=int(ticket_db_id),
                closer_id=interaction.user.id,
                reason=reason,
            )
            await btn_interaction.followup.send(
                embed=obsidian_embed("✅ Ticket Closed", f"Ticket `{ticket_id}` has been closed.", color=discord.Color.green(), client=interaction.client),
                ephemeral=True,
            )
        view = ConfirmView(on_confirm)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
