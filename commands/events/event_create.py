"""Event create command."""
import discord
from discord import app_commands
from datetime import datetime, timezone

from utils import obsidian_embed, parse_time_natural, extract_id, now_utc, is_mod
from database import DB_PATH
import aiosqlite

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def setup(bot, group=None):
    """Register the event_create command."""
    command_decorator = group.command(name="event_create", description="Create an event with RSVP buttons and reminders.") if group else bot.tree.command(name="event_create", description="Create an event with RSVP buttons and reminders.")
    
    @command_decorator
    @app_commands.describe(
        title="Event title",
        when="Natural time: 'tomorrow 8pm', 'Jan 14 7:30pm', etc.",
        description="What are we running?",
        role_ping="Optional role @mention or role ID to ping",
        duration_hours="How long the event runs (default: 2)"
    )
    async def event_create(interaction: discord.Interaction, title: str, when: str, description: str, role_ping: str = "", duration_hours: int = 2):
        # Import bot-specific functions inside to avoid circular imports
        from bot import resolve_channel_id, RSVPView
        from bot import EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME, DB_PATH
        from database import get_configured_channel_id
        import aiosqlite
        
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
        role_id = extract_id(role_ping) if role_ping else None
        mention = ""
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                mention = role.mention

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

        # Event thread for chatter
        thread_id = None
        try:
            thread = await msg.create_thread(name=f"{title} • Ops Thread", auto_archive_duration=1440)
            thread_id = thread.id
            await thread.send(embed=obsidian_embed("Ops Thread", "Coordinate here. Keep it clean, keep it sharp."))
        except Exception:
            pass

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

        await interaction.followup.send("Ops event posted.", ephemeral=True)

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
        role_ping="Optional role to ping"
    )
    @app_commands.choices(day=[app_commands.Choice(name=DAY_NAMES[i], value=str(i)) for i in range(7)])
    async def recurring_add(
        interaction: discord.Interaction,
        title: str,
        description: str,
        day: app_commands.Choice[str],
        hour_utc: int = 18,
        duration_hours: int = 2,
        role_ping: str = "",
    ):
        """Add a recurring event template."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if hour_utc < 0 or hour_utc > 23:
            hour_utc = 18

        day_num = int(day.value)
        role_id = extract_id(role_ping) if role_ping else None

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
