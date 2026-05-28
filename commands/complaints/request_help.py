"""Request help command."""
import discord
from discord import app_commands
import aiosqlite

from core.utils import obsidian_embed, is_mod, display_case_status, now_utc, get_mod_role
from commands.complaints.submit_complaint import case_id_autocomplete
from database import DB_PATH


def setup(bot, group=None):
    """Register the request_help command."""

    async def _lookup_case_status(interaction: discord.Interaction, case_id: str):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Use in a server.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id, status, last_update_at, category, created_at FROM complaints WHERE guild_id=? AND case_id=?",
                (guild.id, case_id),
            )
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Case Not Found",
                    "No case with that ID. Check the ID from your confirmation DM or use `/community my_complaints`.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        user_id, status, last_update_at, category, created_at = int(row[0]), str(row[1]), str(row[2]), row[3], row[4]
        if user_id != interaction.user.id and not (isinstance(interaction.user, discord.Member) and is_mod(interaction.user)):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Access Denied",
                    "You can only view your own case status.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        fields = [
            ("Status", display_case_status(status), True),
            ("Category", category or "—", True),
            ("Filed (UTC)", created_at or "—", True),
            ("Last Update (UTC)", last_update_at, True),
            ("Case ID", case_id, False),
        ]
        embed = obsidian_embed(
            f"📋 Case Status • {case_id}",
            "You'll receive DM updates when staff change the status.",
            color=discord.Color.blurple(),
            fields=fields,
            thumbnail=guild.icon.url if guild.icon else None,
            footer="Use /community case_status to check again",
            client=interaction.client,
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    case_status_decorator = group.command(name="case_status", description="Look up the status of your complaint or help case.") if group else None
    if case_status_decorator:
        @case_status_decorator
        @app_commands.autocomplete(case_id=case_id_autocomplete)
        @app_commands.describe(case_id="Your case ID (e.g., OBS-...) — autocompletes your open cases")
        async def case_status(interaction: discord.Interaction, case_id: str):
            await _lookup_case_status(interaction, case_id)

    my_complaints_decorator = group.command(name="my_complaints", description="List your open complaints/help cases.") if group else None
    if my_complaints_decorator:
        @my_complaints_decorator
        async def my_complaints(interaction: discord.Interaction):
            """List user's open complaints."""
            if not interaction.guild:
                return await interaction.response.send_message("Use in a server.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT case_id, category, status, created_at FROM complaints WHERE guild_id=? AND user_id=? AND status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO') ORDER BY created_at DESC LIMIT 10",
                    (interaction.guild.id, interaction.user.id),
                )
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed("📋 No Open Cases", "You have no open complaints or help requests. Use `/community request_help` to create one.", color=discord.Color.blue(), client=interaction.client),
                    ephemeral=True,
                )
            lines = []
            for case_id, category, status, created in rows:
                lines.append(f"**{case_id}** — {category or '—'} ({display_case_status(status)})")
            await interaction.followup.send(
                embed=obsidian_embed("📋 Your Open Cases", "\n".join(lines), color=discord.Color.blue(), footer="Use /community case_status to check a case", client=interaction.client),
                ephemeral=True,
            )

    command_decorator = group.command(name="request_help", description="Request help or check the status of your help request case.") if group else bot.tree.command(name="request_help", description="Request help or check the status of your help request case.")
    
    @command_decorator
    @app_commands.describe(
        case_id="Your case id to check status (e.g., OBS-...). Leave empty to create new request.",
        category="Category for new request (e.g., harassment / trade / voice conduct)",
        details="Details of your request (required for new requests)",
        evidence="Optional evidence link (for new requests)"
    )
    async def request_help(interaction: discord.Interaction, case_id: str = "", category: str = "", details: str = "", evidence: str = ""):
        from bot import ComplaintModView, log_complaint_action
        from bot import COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME
        from core.channels import ensure_core_channels, resolve_channel_id

        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Use this command in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # If case_id is provided, check status (existing behavior)
        if case_id:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id, status, last_update_at FROM complaints WHERE guild_id=? AND case_id=?",
                    (guild.id, case_id),
                )
                row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Case Not Found",
                        "The case ID you provided was not found. Please check the case ID and try again.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )

            user_id, status, last_update_at = int(row[0]), str(row[1]), str(row[2])
            if user_id != interaction.user.id and not (isinstance(interaction.user, discord.Member) and is_mod(interaction.user)):
                return await interaction.response.send_message(
                    embed=obsidian_embed(
                        "❌ Access Denied",
                        "You can only view your own case status.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )

            fields = [
                ("Status", display_case_status(status), True),
                ("Last Update (UTC)", last_update_at, True),
                ("Case ID", case_id, False),
            ]
            embed = obsidian_embed(
                f"📋 Case Status • {case_id}",
                "",
                color=discord.Color.blurple(),
                fields=fields,
                thumbnail=guild.icon.url if guild.icon else None,
                footer="Use /request_help with case_id to check status again",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Create new help request (case_id not provided)
        if not category or not details:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Missing Information",
                    "To create a new help request, please provide `category` and `details`.\n"
                    "To check an existing case, provide `case_id`.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        
        from database import get_configured_channel_id
        complaints_id = await get_configured_channel_id(guild.id, "complaints_channel_id")
        if not complaints_id:
            await ensure_core_channels(guild)
            complaints_id = await resolve_channel_id(guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
        ch = guild.get_channel(complaints_id) if complaints_id else None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Channel Not Configured",
                    "Complaints channel not configured. Use `/general setup_obsidian` to configure channels.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        
        # Defer response since we'll be creating a post
        await interaction.response.defer(ephemeral=True)

        case_id = f"OBS-{int(now_utc().timestamp())}-{interaction.user.id % 10000}"
        created = now_utc().isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO complaints(guild_id,case_id,user_id,created_at,category,details,evidence,status,staff_thread_id,last_update_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    guild.id,
                    case_id,
                    interaction.user.id,
                    created,
                    category,
                    details,
                    evidence or "",
                    "OPEN",
                    None,
                    created,
                ),
            )
            await db.commit()
        
        mod_role = get_mod_role(guild)
        mention = mod_role.mention if mod_role else "**Administrators**"
        
        desc = f"**Category:** {category}\n\n**Details:**\n{details}"
        if evidence and evidence.strip():
            desc += f"\n\n**Evidence:** {evidence}"
        
        embed = obsidian_embed(
            f"Docket Entry • {case_id}",
            desc,
            color=discord.Color.red(),
            author=interaction.user,
            thumbnail=guild.icon.url if guild.icon else None,
            footer=f"Filed by: {interaction.user} • Case: {case_id}",
            client=interaction.client,
        )
        
        view = ComplaintModView(case_id)
        msg = await ch.send(content=mention, embed=embed, view=view)
        bot.add_view(view)
        
        # Thread for staff discussion (tries private first; falls back)
        thread_id: int | None = None
        thread: discord.Thread | None = None
        try:
            thread = await ch.create_thread(
                name=f"{case_id} • Staff Review",
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Private staff thread for complaint",
            )
            thread_id = thread.id
            if mod_role:
                try:
                    await thread.add_user(interaction.user)
                except Exception:
                    pass
        except Exception:
            try:
                thread = await msg.create_thread(name=f"{case_id} • Staff Review", auto_archive_duration=1440)
                thread_id = thread.id
            except Exception:
                thread = None
        
        if thread_id and thread is not None:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE complaints SET staff_thread_id=? WHERE guild_id=? AND case_id=?",
                    (thread_id, guild.id, case_id),
                )
                await db.commit()
            try:
                await thread.send(embed=obsidian_embed("Staff Thread", "Use this thread for internal notes and resolution steps."))
            except Exception:
                pass
        
        await log_complaint_action(guild, case_id, interaction.user.id, "FILED")
        
        embed = obsidian_embed(
            "✅ Docket Sealed",
            f"Your help request has been sealed as **`{case_id}`**.\n\nYou'll receive DM updates as it progresses.",
            color=discord.Color.green(),
            thumbnail=guild.icon.url if guild.icon else None,
            footer=f"Case: {case_id} • Save this ID to check status",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
