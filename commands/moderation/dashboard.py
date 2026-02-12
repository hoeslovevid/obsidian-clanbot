"""Mod dashboard - overview of open tickets, pending applications, recent warns."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod
from database import DB_PATH
import aiosqlite


def setup(bot, group=None):
    """Register the dashboard command."""
    command_decorator = (
        group.command(name="dashboard", description="View mod overview: open tickets, pending applications, recent warns.")
        if group
        else bot.tree.command(name="dashboard", description="View mod overview: open tickets, pending applications, recent warns.")
    )

    @command_decorator
    async def dashboard(interaction: discord.Interaction):
        """Display mod dashboard with open tickets, pending applications, and recent warns."""
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

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            # Open tickets (urgent first, then escalated, then by activity)
            cur = await db.execute("""
                SELECT ticket_id, subject, user_id, created_at, last_activity_at, tag, priority, escalated
                FROM tickets
                WHERE guild_id=? AND status='open'
                ORDER BY CASE WHEN COALESCE(priority,'normal')='urgent' THEN 0 ELSE 1 END, COALESCE(escalated,0) DESC, last_activity_at ASC
                LIMIT 10
            """, (interaction.guild.id,))
            tickets = await cur.fetchall()

            # Pending applications
            cur = await db.execute("""
                SELECT id, user_id, created_at
                FROM applications
                WHERE guild_id=? AND status='PENDING'
                ORDER BY created_at DESC
                LIMIT 10
            """, (interaction.guild.id,))
            applications = await cur.fetchall()

            # Recent warns (last 7 days)
            cur = await db.execute("""
                SELECT user_id, reason, moderator_id, created_at
                FROM warnings
                WHERE guild_id=?
                ORDER BY created_at DESC
                LIMIT 5
            """, (interaction.guild.id,))
            warns = await cur.fetchall()

        fields = []

        # Open tickets section
        if tickets:
            lines = []
            for row in tickets:
                ticket_id = row[0]
                subject = row[1]
                uid = row[2]
                created = row[3]
                last_at = row[4]
                tag = row[5] if len(row) > 5 else None
                priority = row[6] if len(row) > 6 else None
                user = interaction.guild.get_member(uid)
                uname = user.display_name if user else f"User {uid}"
                tag_str = f" [{tag}]" if tag else ""
                urgent_str = " 🔴" if priority == "urgent" else ""
                escalated = row[7] if len(row) > 7 else 0
                esc_str = " ⚠️" if escalated else ""
                lines.append(f"• **{ticket_id}**{tag_str}{urgent_str}{esc_str} — {uname}\n  _{subject[:50]}{'…' if len(subject or '') > 50 else ''}_")
            fields.append(("🎫 Open Tickets", "\n".join(lines) or "None", False))
        else:
            fields.append(("🎫 Open Tickets", "No open tickets.", False))

        # Pending applications
        if applications:
            lines = []
            for app_id, uid, created in applications:
                user = interaction.guild.get_member(uid)
                uname = user.display_name if user else f"User {uid}"
                lines.append(f"• **#{app_id}** — {uname}")
            fields.append(("📝 Pending Applications", "\n".join(lines) or "None", False))
        else:
            fields.append(("📝 Pending Applications", "No pending applications.", False))

        # Recent warns
        if warns:
            lines = []
            for uid, reason, mod_id, created in warns:
                user = interaction.guild.get_member(uid)
                uname = user.display_name if user else f"User {uid}"
                mod = interaction.guild.get_member(mod_id)
                mname = mod.display_name if mod else f"Mod {mod_id}"
                r = (reason or "—")[:60]
                if len(reason or "") > 60:
                    r += "…"
                lines.append(f"• {uname} by {mname}\n  _{r}_")
            fields.append(("⚠️ Recent Warnings", "\n".join(lines) or "None", False))
        else:
            fields.append(("⚠️ Recent Warnings", "No recent warnings.", False))

        embed = obsidian_embed(
            "🛡️ Mod Dashboard",
            "Overview of items needing attention.",
            color=discord.Color.blue(),
            fields=fields,
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer="Use /ticket, /manage_applications, /mod warn list for details",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
