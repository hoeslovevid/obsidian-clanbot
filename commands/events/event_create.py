"""Event create command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from typing import Optional
from core.utils import obsidian_embed, success_embed, parse_time_natural, now_utc, is_mod, EMBED_COLORS, TIME_AUTOCOMPLETE_CHOICES
from database import DB_PATH
import aiosqlite

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

EVENT_TEMPLATES = {
    "sortie": ("Sortie Run", "Running today's sortie. Bring your A-game!"),
    "eidolon": ("Eidolon Hunt", "Eidolon cap. Cetus night cycle. Bring amp & frame."),
    "railjack": ("Railjack Mission", "Railjack run. Crew positions open."),
    "arbitration": ("Arbitration", "Arbitration endurance. Stay as long as you can."),
    "steel_path": ("Steel Path", "Steel Path missions. High-level content."),
    "duviri": ("Duviri Circuit", "Duviri Circuit run. Weekly rewards."),
    "baro": ("Baro Run", "Heading to Baro. Bring ducats!"),
    "fissure": ("Void Fissure", "Cracking relics. Bring relics to open."),
}


async def _maybe_create_event_thread(
    event_message: discord.Message,
    parent_channel: discord.TextChannel,
    event_name: str,
    start_time: datetime,
) -> Optional[int]:
    """Item 65 — best-effort: create a discussion thread off the event embed.

    Returns the thread id when created, otherwise ``None``. Silently no-ops
    when the bot is missing Manage Threads or the channel doesn't support
    thread creation. The thread name is truncated to Discord's 100-char cap.
    """
    if not isinstance(parent_channel, discord.TextChannel):
        return None
    me = parent_channel.guild.me
    if me is None:
        return None
    perms = parent_channel.permissions_for(me)
    if not (perms.create_public_threads or perms.manage_threads):
        return None

    name = f"{event_name} • {discord.utils.format_dt(start_time, 'R')}"
    if len(name) > 100:
        name = name[:99] + "…"
    try:
        thread = await event_message.create_thread(name=name, auto_archive_duration=1440)
    except discord.HTTPException:
        return None
    try:
        await thread.send(
            f"Discuss the event here. RSVP with the buttons in the parent message.\n{event_message.jump_url}"
        )
    except Exception:
        pass
    return thread.id


async def time_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for natural time strings."""
    current_lower = (current or "").lower()
    choices = []
    for value, label in TIME_AUTOCOMPLETE_CHOICES:
        if not current_lower or current_lower in value.lower():
            choices.append(app_commands.Choice(name=label, value=value))
    return choices[:25]


async def create_event_from_modal(interaction: discord.Interaction, title: str, when_str: str, description: str, duration_hours: int = 2):
    """Create event from modal (Add as Event context menu)."""
    from bot import resolve_channel_id, RSVPView
    from bot import EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME
    from database import get_configured_channel_id
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        return await interaction.followup.send(
            embed=obsidian_embed(
                "❌ Invalid Context",
                "Events can only be created in a server.",
                color=discord.Color.red(),
                client=interaction.client,
            ),
            ephemeral=True,
        )
    dt = parse_time_natural(when_str)
    if not dt:
        return await interaction.followup.send(
            embed=obsidian_embed("❌ Invalid Time", f"Couldn't parse '{when_str}'. Try: tomorrow 8pm, in 2 hours", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    events_id = await get_configured_channel_id(interaction.guild.id, "events_channel_id")
    if not events_id:
        events_id = await resolve_channel_id(interaction.guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
    ch = interaction.guild.get_channel(events_id) if events_id else None
    if not isinstance(ch, discord.TextChannel):
        return await interaction.followup.send("Events channel not configured. Use /general setup_obsidian.", ephemeral=True)
    ts = int(dt.timestamp())
    if duration_hours < 1 or duration_hours > 24:
        duration_hours = 2
    end_ts = ts + (duration_hours * 3600)
    embed = obsidian_embed(
        f"🜂 Ops Order • {title}",
        f"**When:** <t:{ts}:F>  _( <t:{ts}:R> )_\n\n**Ends:** <t:{end_ts}:t>\n\n**Briefing:**\n{description}",
        color=discord.Color.dark_grey(),
    )
    embed.set_author(name=f"Filed by {interaction.user}", icon_url=interaction.user.display_avatar.url)
    embed.set_footer(text="✅ 0  |  ❔ 0  |  ❌ 0")
    msg = await ch.send(embed=embed, view=RSVPView())
    thread_id = await _maybe_create_event_thread(msg, ch, title, dt)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events(guild_id,message_id,creator_id,title,start_ts,end_ts,description,role_id,created_at,reminder_sent,ended,recap_posted,recap_message_id,thread_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (interaction.guild.id, msg.id, interaction.user.id, title, ts, end_ts, description, 0, now_utc().isoformat(), 0, 0, 0, 0, thread_id or 0),
        )
        await db.commit()
    await interaction.followup.send(
        embed=obsidian_embed("✅ Ops Event Posted", f"**{title}** has been posted.", color=EMBED_COLORS["success"], client=interaction.client),
        ephemeral=True,
    )


def setup(bot, group=None):
    """Register the event_create command."""
    command_decorator = group.command(
        name="event_create",
        description="Create an event with RSVP buttons and reminders. E.g. title:'Sortie Run' when:tomorrow 8pm"
    ) if group else bot.tree.command(
        name="event_create",
        description="Create an event with RSVP buttons and reminders. E.g. title:'Sortie Run' when:tomorrow 8pm"
    )
    
    @command_decorator
    @app_commands.autocomplete(when=time_autocomplete)
    @app_commands.choices(template=[app_commands.Choice(name=t[0], value=k) for k, t in EVENT_TEMPLATES.items()])
    @app_commands.describe(
        title="Event title (or use template to override)",
        when="Natural time: 'tomorrow 8pm', 'in 2 hours', 'Jan 14 7:30pm'",
        description="What are we running? (ignored if template used)",
        template="Quick fill: Sortie, Eidolon, Railjack, Fissure, etc.",
        role_ping="Optional role to ping when event is posted",
        duration_hours="How long the event runs (default: 2)"
    )
    async def event_create(interaction: discord.Interaction, when: str, title: str = "Ops Event", description: str = "Coordinate in the thread below.", template: Optional[app_commands.Choice[str]] = None, role_ping: Optional[discord.Role] = None, duration_hours: int = 2):
        # Import bot-specific functions inside to avoid circular imports
        from bot import resolve_channel_id, RSVPView
        from bot import EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME, DB_PATH
        from database import get_configured_channel_id
        import aiosqlite

        if interaction.guild:
            from core.utils import feature_enabled, feature_off_embed  # Item 85
            if not await feature_enabled(interaction.guild.id, "events"):
                return await interaction.response.send_message(
                    embed=feature_off_embed("Events", client=interaction.client),
                    ephemeral=True,
                )

        if template and template.value in EVENT_TEMPLATES:
            t_title, t_desc = EVENT_TEMPLATES[template.value]
            title = t_title
            description = t_desc
        
        dt = parse_time_natural(when)
        if not dt:
            return await interaction.response.send_message(
                "Couldn't parse that time. Try: `tomorrow 8pm`, `Jan 14 7:30pm`, etc.",
                ephemeral=True,
            )

        events_id = await get_configured_channel_id(interaction.guild.id, "events_channel_id")
        if not events_id:
            events_id = await resolve_channel_id(interaction.guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
        ch = interaction.guild.get_channel(events_id) if events_id else None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message(
                "Events channel not configured. Use `/general setup_obsidian` to configure channels.",
                ephemeral=True,
            )

        # Defer response to prevent Discord from retrying the interaction
        await interaction.response.defer(ephemeral=True)

        ts = int(dt.timestamp())
        if duration_hours < 1 or duration_hours > 24:
            duration_hours = 2
        end_ts = ts + (duration_hours * 3600)
        mention = role_ping.mention if role_ping else ""
        role_id = role_ping.id if role_ping else None

        embed = obsidian_embed(
            f"🜂 Ops Order • {title}",
            f"**When:** <t:{ts}:F>  _( <t:{ts}:R> )_\n\n"
            f"**Ends:** <t:{end_ts}:t>  _( <t:{end_ts}:R> )_\n\n"
            f"**Briefing:**\n{description}",
            color=discord.Color.dark_grey(),
        )
        embed.set_author(name=f"Filed by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="✅ 0  |  ❔ 0  |  ❌ 0")

        msg = await ch.send(content=mention if mention else None, embed=embed, view=RSVPView())

        # Auto-thread for discussion (Item 65)
        thread_id = await _maybe_create_event_thread(msg, ch, title, dt)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO events(guild_id,message_id,creator_id,title,start_ts,end_ts,description,role_id,created_at,reminder_sent,ended,recap_posted,recap_message_id,thread_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    interaction.guild.id,
                    msg.id,
                    interaction.user.id,
                    title,
                    ts,
                    end_ts,
                    description,
                    role_id or 0,
                    now_utc().isoformat(),
                    0,
                    0,
                    0,
                    0,
                    thread_id or 0,
                ),
            )
            await db.commit()

        await interaction.followup.send(
            embed=success_embed(
                "Ops Event Posted",
                f"**{title}** has been posted to the events channel.",
                flair="Members can use the ✅/❔/❌ buttons to RSVP.",
                client=interaction.client,
            ),
            ephemeral=True
        )

    events_list_decorator = (
        group.command(name="events_list", description="List upcoming events (today, this week, or your RSVPs).")
        if group else bot.tree.command(name="events_list", description="List upcoming events.")
    )

    @events_list_decorator
    @app_commands.describe(filter_mode="Filter: all upcoming, today, this week, or my RSVPs")
    @app_commands.choices(filter_mode=[
        app_commands.Choice(name="All Upcoming", value="all"),
        app_commands.Choice(name="Today", value="today"),
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="My RSVPs", value="mine"),
    ])
    async def events_list(interaction: discord.Interaction, filter_mode: app_commands.Choice[str] = None):
        """List upcoming events."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        mode = (filter_mode and filter_mode.value) or "all"
        await interaction.response.defer(ephemeral=True)

        now_ts = int(now_utc().timestamp())
        today_start = now_ts - (now_ts % 86400)
        week_end = today_start + (7 * 86400)

        async with aiosqlite.connect(DB_PATH) as db:
            if mode == "mine":
                cur = await db.execute("""
                    SELECT e.message_id, e.title, e.start_ts, e.end_ts, er.response
                    FROM events e
                    JOIN event_rsvps er ON e.guild_id=er.guild_id AND e.message_id=er.message_id
                    WHERE e.guild_id=? AND er.user_id=? AND e.ended=0 AND e.start_ts >= ?
                    ORDER BY e.start_ts ASC LIMIT 15
                """, (interaction.guild.id, interaction.user.id, now_ts))
            elif mode == "today":
                cur = await db.execute("""
                    SELECT message_id, title, start_ts, end_ts
                    FROM events WHERE guild_id=? AND ended=0 AND start_ts >= ? AND start_ts < ?
                    ORDER BY start_ts ASC LIMIT 15
                """, (interaction.guild.id, now_ts, today_start + 86400))
            elif mode == "week":
                cur = await db.execute("""
                    SELECT message_id, title, start_ts, end_ts
                    FROM events WHERE guild_id=? AND ended=0 AND start_ts >= ? AND start_ts < ?
                    ORDER BY start_ts ASC LIMIT 15
                """, (interaction.guild.id, now_ts, week_end))
            else:
                cur = await db.execute("""
                    SELECT message_id, title, start_ts, end_ts
                    FROM events WHERE guild_id=? AND ended=0 AND start_ts >= ?
                    ORDER BY start_ts ASC LIMIT 15
                """, (interaction.guild.id, now_ts))
            rows = await cur.fetchall()

        if not rows:
            label = {"all": "upcoming", "today": "today", "week": "this week", "mine": "you've RSVPed to"}[mode]
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📅 No Events",
                    f"No {label} events. Use `/events event_create` to create one.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        lines = []
        for row in rows:
            title, start_ts = row[1], row[2]
            rsvp = f" [{row[4]}]" if mode == "mine" and len(row) >= 5 else ""
            lines.append(f"**{title}**\n<t:{start_ts}:F> — <t:{start_ts}:R>{rsvp}")

        title_map = {"all": "Upcoming Events", "today": "Events Today", "week": "Events This Week", "mine": "My RSVPs"}
        await interaction.followup.send(
            embed=obsidian_embed(
                f"📅 {title_map[mode]}",
                "\n\n".join(lines),
                color=discord.Color.blue(),
                footer="Jump to event in the events channel to RSVP",
                client=interaction.client,
            ),
            ephemeral=True,
        )

    # Recurring event templates (mods only)
    recurring_add_decorator = (
        group.command(name="recurring_add", description="Add a recurring event template (mods only).")
        if group else bot.tree.command(name="recurring_add", description="Add a recurring event template (mods only).")
    )

    @recurring_add_decorator
    @app_commands.describe(
        title="Event title",
        description="Event description",
        day="Day of week (0=Mon, 6=Sun)",
        hour_utc="Hour in UTC (0-23)",
        duration_hours="Event duration (default 2)",
        role_ping="Optional role to ping when event is posted"
    )
    @app_commands.choices(day=[app_commands.Choice(name=DAY_NAMES[i], value=str(i)) for i in range(7)])
    async def recurring_add(
        interaction: discord.Interaction,
        title: str,
        description: str,
        day: app_commands.Choice[str],
        hour_utc: int = 18,
        duration_hours: int = 2,
        role_ping: Optional[discord.Role] = None,
    ):
        """Add a recurring event template."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if hour_utc < 0 or hour_utc > 23:
            hour_utc = 18

        day_num = int(day.value)
        role_id = role_ping.id if role_ping else None

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO recurring_event_templates
                (guild_id, title, description, day_of_week, hour_utc, minute_utc, duration_hours, role_id, created_by, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 1)
            """, (interaction.guild.id, title, description, day_num, hour_utc, duration_hours, role_id or 0, interaction.user.id, now_utc().isoformat()))
            await db.commit()

        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Recurring Event Added",
                f"**{title}** will auto-post every **{DAY_NAMES[day_num]}** at **{hour_utc:02d}:00 UTC**.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )

    recurring_list_decorator = (
        group.command(name="recurring_list", description="List recurring event templates.")
        if group else bot.tree.command(name="recurring_list", description="List recurring event templates.")
    )

    @recurring_list_decorator
    async def recurring_list(interaction: discord.Interaction):
        """List recurring event templates."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, title, day_of_week, hour_utc, duration_hours, is_active
                FROM recurring_event_templates
                WHERE guild_id=? ORDER BY day_of_week, hour_utc
            """, (interaction.guild.id,))
            rows = await cur.fetchall()

        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📅 No Recurring Events",
                    "No recurring event templates. Mods can add with `/event recurring_add`.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )

        lines = []
        for tid, ttitle, dow, hour, dur, active in rows:
            status = "✅" if active else "❌"
            lines.append(f"{status} **{ttitle}** — {DAY_NAMES[dow]} {hour:02d}:00 UTC ({dur}h) [ID:{tid}]")

        await interaction.followup.send(
            embed=obsidian_embed(
                "📅 Recurring Events",
                "\n".join(lines),
                color=discord.Color.blue(),
                client=interaction.client,
            ),
            ephemeral=True
        )
