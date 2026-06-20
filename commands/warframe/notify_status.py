"""Show all Warframe notification settings at once."""
import discord
from discord import app_commands
import aiosqlite

from core.utils import obsidian_embed
from database import get_guild_setting, DB_PATH


def _fmt_ch(guild: discord.Guild, ch_id: str) -> str:
    """Format channel for display."""
    if not ch_id or not str(ch_id).isdigit():
        return "Not set"
    ch = guild.get_channel(int(ch_id))
    return ch.mention if ch else f"#{ch_id}"


def setup(bot, group=None):
    """Register notify status command under warframe notify group."""
    cmd = group.command(name="status", description="Show all Warframe notification settings.") if group else None
    if not cmd:
        return

    @cmd
    async def notify_status(interaction: discord.Interaction):
        """Display all notify channel settings."""
        if not interaction.guild:
            return await interaction.response.send_message("Use in a server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        lines = []
        guild = interaction.guild

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id, enabled FROM baro_notification_settings WHERE guild_id=?",
                (guild.id,),
            )
            row = await cur.fetchone()
        baro_ch = str(row[0]) if row and row[1] else None
        lines.append(f"**Baro:** {_fmt_ch(guild, baro_ch)}")

        for key, label in [
            ("forum_notify_channel_id", "Forum"),
            ("youtube_notify_channel_id", "YouTube"),
            ("tennogen_notify_channel_id", "TennoGen"),
            ("cycle_notify_channel_id", "Cycle"),
            ("invasion_notify_channel_id", "Invasion"),
            ("archon_notify_channel_id", "Archon"),
            ("alerts_notify_channel_id", "Alerts"),
            ("devstream_notify_channel_id", "Devstream"),
        ]:
            ch_id = await get_guild_setting(guild.id, key)
            lines.append(f"**{label}:** {_fmt_ch(guild, ch_id)}")

        ev_enabled = await get_guild_setting(guild.id, "warframe_event_notify_enabled")
        lines.append(f"**Warframe Events:** {'Enabled' if ev_enabled == '1' else 'Disabled'}")

        embed = obsidian_embed(
            "📢 Notification Settings",
            "\n".join(lines),
            color=discord.Color.blue(),
            footer="Use /wfnotify why_dm · test_ping · configure",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @group.command(name="why_dm", description="Why didn't I get a DM? Check your notification settings.")
    async def why_dm(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Use in a server.", ephemeral=True)
        from core.notify_explain import build_notify_explain_embed

        embed = await build_notify_explain_embed(
            interaction.guild, interaction.user, client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="test_ping", description="Send a test DM to verify bot notifications work.")
    async def test_ping(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Use in a server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        from core.safe_send import safe_dm_or_hint

        embed = obsidian_embed(
            "🔔 Test ping",
            "If you received this in DMs, personal notifications are working!\n\n"
            "Channel alerts (Baro, cycles) are separate — configure those with `/wfnotify configure`.",
            color=discord.Color.green(),
            client=interaction.client,
        )
        sent = await safe_dm_or_hint(
            interaction.user,
            interaction,
            what_failed="Couldn't send the test DM.",
            embed=embed,
        )
        if sent:
            await interaction.followup.send("✅ Test DM sent — check your DMs.", ephemeral=True)
        else:
            await interaction.followup.send(
                "Couldn't deliver a test DM. See the hint above or run `/wfnotify why_dm`.",
                ephemeral=True,
            )
