"""Application management command for moderators."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the manage_applications command."""
    command_decorator = group.command(name="manage_applications", description="View and manage clan applications (moderators only).") if group else bot.tree.command(name="manage_applications", description="View and manage clan applications (moderators only).")
    
    @command_decorator
    @app_commands.describe(
        status="Filter by status (default: all)",
        limit="Number of applications to show (default: 10, max: 25)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="In Progress", value="IN_PROGRESS"),
        app_commands.Choice(name="Pending", value="PENDING"),
        app_commands.Choice(name="Approved", value="APPROVED"),
        app_commands.Choice(name="Rejected", value="REJECTED"),
    ])
    async def manage_applications(
        interaction: discord.Interaction,
        status: app_commands.Choice[str] = None,
        limit: int = 10
    ):
        """View and manage applications."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        status_filter = status.value if status and status.value != "all" else None
        
        if limit < 1 or limit > 25:
            limit = 10
        
        # Get applications from database
        async with aiosqlite.connect(DB_PATH) as db:
            if status_filter:
                cur = await db.execute("""
                    SELECT id, user_id, status, created_at, submitted_at, reviewed_by
                    FROM applications
                    WHERE guild_id = ? AND status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (interaction.guild.id, status_filter, limit))
            else:
                cur = await db.execute("""
                    SELECT id, user_id, status, created_at, submitted_at, reviewed_by
                    FROM applications
                    WHERE guild_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (interaction.guild.id, limit))
            rows = await cur.fetchall()
        
        if not rows:
            status_text = f" with status '{status_filter}'" if status_filter else ""
            desc = f"No applications{status_text} found.\n\n_→ Applicants can use `/community apply` to submit. Try a different status filter if needed._"
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📝 No Applications Found",
                    desc,
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed with applications
        fields = []
        for app_id, user_id, app_status, created_at, submitted_at, reviewed_by in rows:
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            
            status_emoji = {
                "IN_PROGRESS": "⏳",
                "PENDING": "📝",
                "APPROVED": "✅",
                "REJECTED": "❌"
            }.get(app_status, "❓")
            
            value = f"**Status:** {status_emoji} {app_status}\n"
            value += f"**By:** {username}\n"
            value += f"**ID:** #{app_id}"
            
            fields.append((f"Application #{app_id}", value, False))
        
        status_display = status_filter if status_filter else "All"
        embed = obsidian_embed(
            f"📝 Applications ({status_display})",
            f"Showing {len(rows)} application(s). Use buttons on individual application messages to manage them.",
            color=discord.Color.blue(),
            fields=fields,
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{len(rows)} application(s) • Filter: {status_display}",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
