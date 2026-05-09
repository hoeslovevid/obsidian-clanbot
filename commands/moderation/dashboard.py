"""Mod dashboard - overview of open tickets, pending applications, recent warns, server stats."""
import discord
from discord import app_commands

from datetime import datetime, timezone
from core.utils import obsidian_embed, is_mod, format_timestamp_readable
from database import DB_PATH
import aiosqlite


async def _build_mod_dashboard_embed(
    guild: discord.Guild, client: discord.Client
) -> discord.Embed:
    """Query DB and return the mod dashboard embed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ticket_id, subject, user_id, created_at, last_activity_at, tag, priority, escalated
            FROM tickets
            WHERE guild_id=? AND status='open'
            ORDER BY CASE WHEN COALESCE(priority,'normal')='urgent' THEN 0 ELSE 1 END,
                     COALESCE(escalated,0) DESC, last_activity_at ASC
            LIMIT 10
        """, (guild.id,))
        tickets = await cur.fetchall()

        cur = await db.execute("""
            SELECT id, user_id, created_at
            FROM applications
            WHERE guild_id=? AND status='PENDING'
            ORDER BY created_at DESC
            LIMIT 10
        """, (guild.id,))
        applications = await cur.fetchall()

        cur = await db.execute("""
            SELECT user_id, reason, moderator_id, created_at
            FROM warnings
            WHERE guild_id=?
            ORDER BY created_at DESC
            LIMIT 5
        """, (guild.id,))
        warns = await cur.fetchall()

    fields = []

    if tickets:
        lines = []
        for row in tickets:
            ticket_id, subject, uid, created, last_at = row[0], row[1], row[2], row[3], row[4]
            tag      = row[5] if len(row) > 5 else None
            priority = row[6] if len(row) > 6 else None
            escalated = row[7] if len(row) > 7 else 0
            user  = guild.get_member(uid)
            uname = user.display_name if user else f"User {uid}"
            tag_str     = f" [{tag}]" if tag else ""
            urgent_str  = " 🔴" if priority == "urgent" else ""
            esc_str     = " ⚠️" if escalated else ""
            lines.append(
                f"• **{ticket_id}**{tag_str}{urgent_str}{esc_str} — {uname}\n"
                f"  _{subject[:50]}{'…' if len(subject or '') > 50 else ''}_"
            )
        fields.append(("🎫 Open Tickets", "\n".join(lines), False))
    else:
        fields.append(("🎫 Open Tickets", "No open tickets.", False))

    if applications:
        lines = []
        for app_id, uid, created in applications:
            user  = guild.get_member(uid)
            uname = user.display_name if user else f"User {uid}"
            lines.append(f"• **#{app_id}** — {uname}")
        fields.append(("📝 Pending Applications", "\n".join(lines), False))
    else:
        fields.append(("📝 Pending Applications", "No pending applications.", False))

    if warns:
        lines = []
        for uid, reason, mod_id, created in warns:
            user  = guild.get_member(uid)
            uname = user.display_name if user else f"User {uid}"
            mod   = guild.get_member(mod_id)
            mname = mod.display_name if mod else f"Mod {mod_id}"
            r = (reason or "—")[:60]
            if len(reason or "") > 60:
                r += "…"
            lines.append(f"• {uname} by {mname}\n  _{r}_")
        fields.append(("⚠️ Recent Warnings", "\n".join(lines), False))
    else:
        fields.append(("⚠️ Recent Warnings", "No recent warnings.", False))

    refreshed = format_timestamp_readable(datetime.now(timezone.utc))
    return obsidian_embed(
        "🛡️ Mod Dashboard",
        "Overview of items needing attention.",
        category="moderation",
        fields=fields,
        thumbnail=guild.icon.url if guild.icon else None,
        footer=f"Refreshed {refreshed}  ·  /ticket · /manage_applications · /mod warn list",
        client=client,
    )


async def _build_stats_dashboard_embed(
    guild: discord.Guild, client: discord.Client
) -> discord.Embed:
    """Query DB and return the server stats embed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(balance),0), COALESCE(SUM(total_earned),0), COUNT(*) FROM user_balances WHERE guild_id=?",
            (guild.id,),
        )
        eco = await cur.fetchone()
        total_coins, total_earned, economy_users = eco[0] or 0, eco[1] or 0, eco[2] or 0

        cur = await db.execute(
            "SELECT COALESCE(SUM(messages_sent),0), COALESCE(SUM(voice_minutes),0), COALESCE(SUM(events_attended),0) FROM activity_stats WHERE guild_id=?",
            (guild.id,),
        )
        act = await cur.fetchone()
        total_messages, total_voice_mins, total_events = act[0] or 0, act[1] or 0, act[2] or 0

        cur = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),0) FROM tickets WHERE guild_id=?",
            (guild.id,),
        )
        tix = await cur.fetchone()
        tickets_total, tickets_open = tix[0] or 0, tix[1] or 0

        cur = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END),0) FROM applications WHERE guild_id=?",
            (guild.id,),
        )
        app = await cur.fetchone()
        apps_total, apps_pending = app[0] or 0, app[1] or 0

    member_count = guild.member_count or 0
    text_chans   = sum(1 for c in guild.channels if isinstance(c, discord.TextChannel))
    voice_chans  = sum(1 for c in guild.channels if isinstance(c, discord.VoiceChannel))
    role_count   = len(guild.roles)
    voice_hours  = total_voice_mins // 60
    voice_mins   = total_voice_mins % 60
    voice_str    = f"{voice_hours}h {voice_mins}m" if voice_hours > 0 else f"{voice_mins}m"

    fields = [
        ("👥 Server",   f"**Members:** {member_count:,}\n**Roles:** {role_count}\n**Channels:** {text_chans} text, {voice_chans} voice", True),
        ("💰 Economy",  f"**Total Coins:** {total_coins:,}\n**Earned (all-time):** {total_earned:,}\n**Users with balance:** {economy_users:,}", True),
        ("📊 Activity", f"**Messages:** {total_messages:,}\n**Voice:** {voice_str}\n**Event RSVPs:** {total_events:,}", True),
        ("🎫 Support",  f"**Tickets:** {tickets_open} open / {tickets_total} total\n**Applications:** {apps_pending} pending / {apps_total} total", True),
    ]

    refreshed = format_timestamp_readable(datetime.now(timezone.utc))
    return obsidian_embed(
        "📈 Server Stats Dashboard",
        f"Analytics for **{guild.name}**",
        category="moderation",
        fields=fields,
        thumbnail=guild.icon.url if guild.icon else None,
        footer=f"Refreshed {refreshed}",
        client=client,
    )


class ModDashboardView(discord.ui.View):
    """Refresh button for the mod dashboard."""

    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "You must be a moderator to refresh this.", ephemeral=True
            )
        await interaction.response.defer()
        embed = await _build_mod_dashboard_embed(self.guild, interaction.client)
        await interaction.edit_original_response(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


class StatsDashboardView(discord.ui.View):
    """Refresh button for the server stats dashboard."""

    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "You must be a moderator to refresh this.", ephemeral=True
            )
        await interaction.response.defer()
        embed = await _build_stats_dashboard_embed(self.guild, interaction.client)
        await interaction.edit_original_response(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


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
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        embed = await _build_mod_dashboard_embed(interaction.guild, interaction.client)
        view  = ModDashboardView(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    stats_decorator = (
        group.command(name="stats_dashboard", description="View server analytics: members, economy, activity.")
        if group
        else bot.tree.command(name="stats_dashboard", description="View server analytics: members, economy, activity.")
    )

    @stats_decorator
    async def stats_dashboard(interaction: discord.Interaction):
        """Display server stats dashboard."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Sorry, but you are not an Administrator in this server.",
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        embed = await _build_stats_dashboard_embed(interaction.guild, interaction.client)
        view  = StatsDashboardView(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
