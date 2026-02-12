"""Ticket escalation and mod tools (mods only)."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import set_guild_setting, DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register ticket config commands."""
    command_decorator = (
        group.command(name="ticket_escalation", description="Set the role to ping when a ticket is escalated.")
        if group
        else bot.tree.command(name="ticket_escalation", description="Set the role to ping when a ticket is escalated.")
    )

    @command_decorator
    @app_commands.describe(role="Role to ping when a ticket is escalated (leave empty to clear)")
    async def ticket_escalation(interaction: discord.Interaction, role: discord.Role = None):
        """Set or clear the ticket escalation role."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )

        if role:
            await set_guild_setting(interaction.guild.id, "ticket_escalation_role_id", str(role.id))
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "✅ Escalation Role Set",
                    f"When staff click **Escalate** on a ticket, {role.mention} will be pinged.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        else:
            await set_guild_setting(interaction.guild.id, "ticket_escalation_role_id", "")
            await interaction.response.send_message(
                embed=obsidian_embed(
                    "✅ Escalation Role Cleared",
                    "Escalation role has been removed. The Escalate button will still mark tickets as escalated but will not ping any role.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

    search_decorator = (
        group.command(name="search_notes", description="Search ticket notes by keyword.")
        if group
        else bot.tree.command(name="search_notes", description="Search ticket notes by keyword.")
    )

    @search_decorator
    @app_commands.describe(query="Keyword or phrase to search for in ticket notes", limit="Max results (default 15)")
    async def search_notes(interaction: discord.Interaction, query: str, limit: int = 15):
        """Search internal ticket notes by content."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )
        if limit < 1 or limit > 30:
            limit = 15

        await interaction.response.defer(ephemeral=True)

        pattern = f"%{query.strip()}%"
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT tn.id, tn.ticket_id, tn.note, tn.created_at, tn.author_id, t.ticket_id as ticket_slug, t.subject, t.status
                FROM ticket_notes tn
                JOIN tickets t ON tn.ticket_id = t.id
                WHERE t.guild_id = ? AND tn.note LIKE ?
                ORDER BY tn.created_at DESC
                LIMIT ?
            """, (interaction.guild.id, pattern, limit))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🔍 No Matches",
                    f"No ticket notes found containing: **{query}**",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        lines = []
        for note_id, ticket_db_id, note, created_at, author_id, ticket_slug, subject, status in rows:
            author = interaction.guild.get_member(author_id)
            author_name = author.display_name if author else f"User {author_id}"
            # Truncate note for display
            note_preview = (note[:150] + "…") if len(note) > 150 else note
            lines.append(f"**Ticket `{ticket_slug}`** ({status}) — by {author_name}\n_{note_preview}_")

        embed = obsidian_embed(
            f"🔍 Note Search: {query}",
            "\n\n".join(lines),
            color=discord.Color.blue(),
            footer=f"{len(rows)} result(s)",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
