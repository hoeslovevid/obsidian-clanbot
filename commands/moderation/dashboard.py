"""Mod dashboard - overview of open tickets, pending applications, recent warns, server stats."""
import time
import discord
from discord import app_commands

from datetime import datetime, timezone, date
from core.embed_templates import embed_template
from core.embed_footers import footer_for
from core.utils import obsidian_embed, is_mod, format_timestamp_readable
from database import DB_PATH, get_auto_mod_settings, get_guild_setting
from commands.moderation.incident_mode import get_incident_mode
import aiosqlite

_DASHBOARD_CACHE_TTL = 600.0  # 10 minutes
_mod_dashboard_cache: dict[int, tuple[float, discord.Embed]] = {}


async def _build_mod_dashboard_embed(
    guild: discord.Guild, client: discord.Client
) -> discord.Embed:
    """Query DB and return the mod dashboard embed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ticket_id, subject, user_id, created_at, last_activity_at, tag, priority, escalated,
                   first_response_at
            FROM tickets
            WHERE guild_id=? AND status='open'
            ORDER BY CASE WHEN COALESCE(priority,'normal')='urgent' THEN 0 ELSE 1 END,
                     COALESCE(escalated,0) DESC, last_activity_at ASC
            LIMIT 10
        """, (guild.id,))
        tickets = await cur.fetchall()

        cur = await db.execute("""
            SELECT COUNT(*) FROM tickets
            WHERE guild_id=? AND status='open'
              AND (first_response_at IS NULL OR first_response_at='')
        """, (guild.id,))
        awaiting_first_response = int((await cur.fetchone())[0] or 0)

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

        cur = await db.execute("""
            SELECT COUNT(*) FROM complaints
            WHERE guild_id=? AND status IN ('OPEN','ACKNOWLEDGED','NEEDS INFO')
        """, (guild.id,))
        open_incidents = (await cur.fetchone())[0] or 0

        cur = await db.execute(
            "SELECT COUNT(*) FROM lfg_posts WHERE guild_id=? AND status='OPEN'",
            (guild.id,),
        )
        open_lfg = int((await cur.fetchone())[0] or 0)

        goal_line = ""
        try:
            cur = await db.execute(
                """
                SELECT metric, target FROM server_goals
                WHERE guild_id=? AND completed=0 ORDER BY week_end DESC LIMIT 1
                """,
                (guild.id,),
            )
            goal_row = await cur.fetchone()
            if goal_row:
                goal_line = f"\n**Server goal:** {goal_row[0]} → {goal_row[1]:,}"
        except Exception:
            pass

        today_iso = date.today().isoformat()
        cur = await db.execute("""
            SELECT COUNT(*) FROM warnings
            WHERE guild_id=? AND date(created_at) = ?
        """, (guild.id, today_iso))
        warns_today = (await cur.fetchone())[0] or 0

        warn_escalation = ""
        try:
            cur = await db.execute(
                """
                SELECT user_id, COUNT(*) AS c FROM warnings
                WHERE guild_id=? AND datetime(created_at) >= datetime('now', '-30 days')
                GROUP BY user_id HAVING c >= 3
                ORDER BY c DESC LIMIT 3
                """,
                (guild.id,),
            )
            esc = await cur.fetchall()
            if esc:
                parts = [f"<@{uid}> ({cnt})" for uid, cnt in esc]
                warn_escalation = f"\n**Warn ladder:** {', '.join(parts)} — consider timeout review"
        except Exception:
            pass

    automod = await get_auto_mod_settings(guild.id)
    if automod and automod.get("enabled"):
        rules = []
        if automod.get("spam_enabled"):
            rules.append("spam")
        if automod.get("caps_enabled"):
            rules.append("caps")
        if automod.get("links_enabled"):
            rules.append("links")
        if automod.get("mention_enabled"):
            rules.append("mentions")
        automod_summary = f"✅ **ON** · {', '.join(rules) if rules else 'no rules'}"
    elif automod:
        automod_summary = "⏸️ **Configured** · disabled"
    else:
        automod_summary = "— not configured"

    incident_on = await get_incident_mode(guild.id)
    incident_summary = "🚨 **ACTIVE**" if incident_on else "✅ Off"

    from core.maintenance import maintenance_enabled, maintenance_message

    ops_alerts = ""
    if maintenance_enabled():
        ops_alerts += f"\n🔧 **Maintenance:** {maintenance_message()}"
    if incident_on:
        ops_alerts += "\n📋 Use **Staff runbook** on `/admin dashboard` for announcement drafts."

    sla_note = ""
    if awaiting_first_response:
        sla_note = f"\n**Tickets awaiting staff reply:** {awaiting_first_response}"
    try:
        sla_raw = await get_guild_setting(guild.id, "ticket_sla_hours")
        sla_h = int(sla_raw) if sla_raw and str(sla_raw).isdigit() else 4
        sla_note += f"\n**Ticket SLA target:** {sla_h}h first response"
    except Exception:
        pass

    fields = [
        (
            "📋 Officer live board",
            f"**Open incidents:** {open_incidents}\n"
            f"**Open LFG:** {open_lfg}\n"
            f"**Warns today:** {warns_today}\n"
            f"**Incident mode:** {incident_summary}\n"
            f"**Automod:** {automod_summary}"
            + ops_alerts
            + sla_note
            + goal_line
            + warn_escalation,
            False,
        ),
    ]

    if tickets:
        lines = []
        for row in tickets:
            ticket_id, subject, uid, created, last_at = row[0], row[1], row[2], row[3], row[4]
            tag      = row[5] if len(row) > 5 else None
            priority = row[6] if len(row) > 6 else None
            escalated = row[7] if len(row) > 7 else 0
            first_resp = row[8] if len(row) > 8 else None
            user  = guild.get_member(uid)
            uname = user.display_name if user else f"User {uid}"
            tag_str     = f" [{tag}]" if tag else ""
            urgent_str  = " 🔴" if priority == "urgent" else ""
            esc_str     = " ⚠️" if escalated else ""
            sla_str     = " ⏳" if not first_resp else ""
            lines.append(
                f"• **{ticket_id}**{tag_str}{urgent_str}{esc_str}{sla_str} — {uname}\n"
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

    try:
        from core.command_prune import format_guild_usage_embed_body

        usage_body = await format_guild_usage_embed_body(client, guild.id)
        if usage_body:
            fields.append(("📊 Command KPI", usage_body[:1024], False))
    except Exception:
        pass

    refreshed = format_timestamp_readable(datetime.now(timezone.utc))
    embed = embed_template(
        "showcase",
        "🛡️ Mod Dashboard",
        "Overview of items needing attention.",
        category="moderation",
        fields=fields,
        thumbnail=guild.icon.url if guild.icon else None,
        footer=f"Refreshed {refreshed} · {footer_for('community_ticket')}",
        client=client,
    )
    if guild.owner:
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    return embed


async def get_mod_dashboard_embed(
    guild: discord.Guild,
    client: discord.Client,
    *,
    force_refresh: bool = False,
) -> discord.Embed:
    """Cached mod dashboard (10 min) unless force_refresh."""
    now = time.monotonic()
    if not force_refresh:
        entry = _mod_dashboard_cache.get(guild.id)
        if entry and (now - entry[0]) < _DASHBOARD_CACHE_TTL:
            return entry[1]
    embed = await _build_mod_dashboard_embed(guild, client)
    _mod_dashboard_cache[guild.id] = (now, embed)
    return embed


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


class _LockChannelPicker(discord.ui.View):
    """Stage 2 for the 🔒 Lock quick-action — pick a channel to lock."""

    def __init__(self, invoker_id: int):
        super().__init__(timeout=120)
        self.invoker_id = invoker_id
        select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Pick a channel to lock…",
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select  # type: ignore[assignment]
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.invoker_id

    async def _on_select(self, interaction: discord.Interaction):
        select: discord.ui.ChannelSelect = self.children[0]  # type: ignore[assignment]
        channel = select.values[0]
        # ChannelSelect returns app_commands.AppCommandChannel — resolve to a real channel
        ch = interaction.guild.get_channel(int(channel.id))
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message("Channel not found.", ephemeral=True)
        from commands.moderation.lock import apply_channel_lock
        try:
            await apply_channel_lock(ch, actor=interaction.user, lock=True)
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Missing Permission",
                    f"I can't change permissions on {ch.mention}.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔒 Channel Locked",
                f"{ch.mention} is now locked for @everyone. Use `/unlock` in that channel to restore.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )


class ModDashboardView(discord.ui.View):
    """Refresh + quick-action buttons for the mod dashboard (Item 22)."""

    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=300)
        self.guild = guild

    async def _require_mod(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message(
                "You must be a moderator to use this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        await interaction.response.defer()
        embed = await get_mod_dashboard_embed(self.guild, interaction.client, force_refresh=True)
        from core.dashboard_layout import ModDashboardSnapshotLayout
        from core.help_layout import help_layout_v2_enabled

        if help_layout_v2_enabled():
            try:
                snap_fields = [(f.name, f.value, f.inline) for f in embed.fields[:3]]

                async def _snap_refresh(inter: discord.Interaction):
                    await self.refresh(inter, button)

                layout = ModDashboardSnapshotLayout(
                    title="🛡️ Mod Dashboard",
                    intro=embed.description or "Overview of items needing attention.",
                    fields=snap_fields,
                    on_refresh=_snap_refresh,
                )
                await interaction.edit_original_response(view=layout)
                return
            except Exception:
                pass
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Lock #channel", style=discord.ButtonStyle.danger, emoji="🔒")
    async def lock_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🔒 Lock a Channel",
                "Pick a channel below to lock @everyone out of sending messages.",
                category="moderation",
                client=interaction.client,
            ),
            view=_LockChannelPicker(interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Incident Mode", style=discord.ButtonStyle.primary, emoji="🚨")
    async def incident_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        from commands.moderation.incident_mode import toggle_incident_mode
        new_state = await toggle_incident_mode(
            self.guild.id,
            guild=self.guild,
            client=interaction.client,
        )
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🚨 Incident Mode " + ("Enabled" if new_state else "Disabled"),
                "Incident mode is now **{}**. Default duration: 60 minutes.".format("ON" if new_state else "OFF"),
                color=discord.Color.orange() if new_state else discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Raid Protection", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def raid_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        from commands.moderation.raid_protection import toggle_raid_protection
        new_state = await toggle_raid_protection(self.guild.id)
        await interaction.response.send_message(
            embed=obsidian_embed(
                "🛡️ Raid Protection " + ("Enabled" if new_state else "Disabled"),
                "Raid protection is now **{}**. Configure thresholds with `/mod raid_protection`.".format(
                    "ON" if new_state else "OFF"
                ),
                color=discord.Color.green() if new_state else discord.Color.orange(),
                client=interaction.client,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Recent Warns", style=discord.ButtonStyle.secondary, emoji="📝")
    async def warns_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._require_mod(interaction):
            return
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT user_id, reason, moderator_id, created_at
                FROM warnings
                WHERE guild_id=?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (self.guild.id,),
            )
            warns = await cur.fetchall()
        if not warns:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "📝 Recent Warnings",
                    "No recent warnings on record.",
                    category="moderation",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = []
        for uid, reason, mod_id, _created in warns:
            user = self.guild.get_member(uid)
            mod = self.guild.get_member(mod_id)
            uname = user.display_name if user else f"User {uid}"
            mname = mod.display_name if mod else f"Mod {mod_id}"
            r = (reason or "—").strip()
            r = r[:80] + ("…" if len(r) > 80 else "")
            lines.append(f"• **{uname}** by {mname} — _{r}_")
        await interaction.response.send_message(
            embed=obsidian_embed(
                "📝 Recent Warnings (last 10)",
                "\n".join(lines),
                category="moderation",
                client=interaction.client,
            ),
            ephemeral=True,
        )

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
        embed = await get_mod_dashboard_embed(interaction.guild, interaction.client)
        from core.mod_runbook import ModRunbookView
        view = ModDashboardView(interaction.guild)
        runbook = ModRunbookView(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await interaction.followup.send(
            embed=obsidian_embed(
                "📋 Staff runbook",
                "Copy-paste announcement drafts for common situations.",
                category="moderation",
                client=interaction.client,
            ),
            view=runbook,
            ephemeral=True,
        )

    inbox_decorator = (
        group.command(
            name="inbox",
            description="Staff inbox — tickets, apps, suggestions, LFG, and setup gaps.",
        )
        if group
        else bot.tree.command(
            name="inbox",
            description="Staff inbox — tickets, apps, suggestions, LFG, and setup gaps.",
        )
    )

    @inbox_decorator
    async def mod_inbox(interaction: discord.Interaction):
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
        from core.mod_inbox import build_mod_inbox_embed

        embed = await build_mod_inbox_embed(interaction.guild, client=interaction.client)
        await interaction.followup.send(embed=embed, ephemeral=True)

    usage_decorator = (
        group.command(
            name="usage_report",
            description="Command heatmap + prune candidates for this server (mods only).",
        )
        if group
        else bot.tree.command(
            name="usage_report",
            description="Command heatmap + prune candidates for this server (mods only).",
        )
    )

    @usage_decorator
    async def usage_report(interaction: discord.Interaction):
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
        from core.command_prune import format_guild_usage_embed_body, guild_usage_summary
        from core.command_usage_report import format_prune_hint

        top, unused = await guild_usage_summary(interaction.client, interaction.guild.id, unused_limit=25)
        body = await format_guild_usage_embed_body(interaction.client, interaction.guild.id)
        hint = format_prune_hint(unused, min_count=5)
        desc = body
        if hint and hint not in desc:
            desc = f"{desc}\n\n{hint}" if desc else hint
        embed = obsidian_embed(
            "📊 Command usage report",
            desc or "_No usage data yet._",
            category="moderation",
            client=interaction.client,
        )
        if top:
            embed.add_field(
                name="Registered vs used",
                value=f"**Top tracked:** {len(top)} · **Zero-use sample:** {len(unused)}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

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
