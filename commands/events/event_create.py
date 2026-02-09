"""Event create command."""
import discord
from discord import app_commands

from utils import obsidian_embed, parse_time_natural, extract_id, now_utc


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
        from bot import ensure_core_channels, resolve_channel_id, RSVPView
        from bot import EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME, DB_PATH
        import aiosqlite
        
        dt = parse_time_natural(when)
        if not dt:
            return await interaction.response.send_message(
                "Couldn't parse that time. Try: `tomorrow 8pm`, `Jan 14 7:30pm`, etc.",
                ephemeral=True,
            )

        await ensure_core_channels(interaction.guild)
        events_id = await resolve_channel_id(interaction.guild, "events_channel_id", EVENTS_CHANNEL_ID, EVENTS_CHANNEL_NAME)
        ch = interaction.guild.get_channel(events_id) if events_id else None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message(
                "Events channel not configured. Set EVENTS_CHANNEL_ID or enable AUTO_SETUP.",
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
