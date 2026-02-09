"""Request help command."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod, display_case_status, now_utc, get_mod_role


def setup(bot, group=None):
    """Register the request_help command."""
    command_decorator = group.command(name="request_help", description="Request help or check the status of your help request case.") if group else bot.tree.command(name="request_help", description="Request help or check the status of your help request case.")
    
    @command_decorator
    @app_commands.describe(
        case_id="Your case id to check status (e.g., OBS-...). Leave empty to create new request.",
        category="Category for new request (e.g., harassment / trade / voice conduct)",
        details="Details of your request (required for new requests)",
        evidence="Optional evidence link (for new requests)"
    )
    async def request_help(interaction: discord.Interaction, case_id: str = "", category: str = "", details: str = "", evidence: str = ""):
        # Import bot-specific functions inside to avoid circular imports
        from bot import ensure_core_channels, resolve_channel_id, ComplaintModView, log_complaint_action
        from bot import COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME, DB_PATH
        import aiosqlite
        
        # If case_id is provided, check status (existing behavior)
        if case_id:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT user_id, status, last_update_at FROM complaints WHERE guild_id=? AND case_id=?",
                    (interaction.guild.id, case_id),
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

            return await interaction.response.send_message(
                embed=obsidian_embed(
                    f"📋 Case Status • {case_id}",
                    f"**Status:** {display_case_status(status)}\n**Last Update (UTC):** {last_update_at}",
                    color=discord.Color.blurple(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        
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
        
        await ensure_core_channels(interaction.guild)
        complaints_id = await resolve_channel_id(interaction.guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
        ch = interaction.guild.get_channel(complaints_id) if complaints_id else None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Channel Not Configured",
                    "Complaints channel not configured. Set COMPLAINTS_CHANNEL_ID or enable AUTO_SETUP.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        
        # Defer response since we'll be creating a post
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
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
        
        embed = obsidian_embed(f"Docket Entry • {case_id}", desc, color=discord.Color.red())
        embed.set_footer(text=f"Filed by: {interaction.user} • {interaction.user.id}")
        
        view = ComplaintModView(case_id)
        msg = await ch.send(content=mention, embed=embed, view=view)
        bot.add_view(view)
        
        # Thread for staff discussion (tries private first; falls back)
        thread_id = None
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
        
        if thread_id:
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
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Docket Sealed",
                f"Your help request has been sealed as **`{case_id}`**.\n\nYou'll receive DM updates as it progresses.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
