"""/admin setup_status — at-a-glance view of configured vs missing features."""
import aiosqlite
import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS, is_mod, render_bar
from database import DB_PATH, get_configured_channel_id, get_log_channel_id

# (label, guild_settings key, setup command path for the CTA)
_CORE_CHECKS = [
    ("📅 Events channel", "events_channel_id", "general setup_obsidian"),
    ("⭐ Level-up announcements", "xp_levelup_channel_id", "general setup_obsidian"),
    ("🎙️ Join-to-create voice", "create_vc_channel_id", "general setup_obsidian"),
]
_WF_CHECKS = [
    ("🔔 Warframe alerts feed", "alerts_notify_channel_id", "wfnotify configure"),
    ("📰 Warframe forum feed", "forum_notify_channel_id", "wfnotify configure"),
    ("▶️ Warframe YouTube feed", "youtube_notify_channel_id", "wfnotify configure"),
    ("📺 Warframe devstreams", "devstream_notify_channel_id", "wfnotify configure"),
]
_MOD_CHECKS = [
    ("🛡️ Mod audit log", "audit", "mod logging setup"),
    ("⚠️ Bot error log", "bot_error", "mod logging setup"),
    ("📋 Ticket transcripts", "ticket_transcript", "mod logging setup"),
]


async def compute_setup_health(guild: discord.Guild) -> tuple[int, int, str, str, str, str]:
    """Return (configured, total, core_block, wf_block, mod_block, extra_block)."""
    from core.command_mentions import command_mention

    configured = 0
    total = 0

    async def _channel_section(checks):
        nonlocal configured, total
        rows = []
        for label, key, cta in checks:
            total += 1
            ch_id = await get_configured_channel_id(guild.id, key)
            ch = guild.get_channel(ch_id) if ch_id else None
            if ch_id and ch:
                configured += 1
                rows.append(f"✅ {label} → {ch.mention}")
            elif ch_id and not ch:
                rows.append(f"⚠️ {label} → set, but channel is missing/deleted")
            else:
                rows.append(f"❌ {label} — set up with {command_mention(cta, fallback=f'`/{cta}`')}")
        return "\n".join(rows)

    async def _log_section(checks):
        nonlocal configured, total
        rows = []
        for label, log_type, cta in checks:
            total += 1
            ch_id = await get_log_channel_id(guild.id, log_type)
            ch = guild.get_channel(ch_id) if ch_id else None
            if ch_id and ch:
                configured += 1
                rows.append(f"✅ {label} → {ch.mention}")
            elif ch_id and not ch:
                rows.append(f"⚠️ {label} → set, but channel is missing/deleted")
            else:
                rows.append(f"❌ {label} — set up with {command_mention(cta, fallback=f'`/{cta}`')}")
        return "\n".join(rows)

    async def _extra_section():
        nonlocal configured, total
        from core.command_mentions import command_mention

        rows = []
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id FROM starboard_settings WHERE guild_id=?",
                (guild.id,),
            )
            row = await cur.fetchone()
            cur2 = await db.execute(
                "SELECT channel_id FROM update_log_settings WHERE guild_id=? AND channel_id IS NOT NULL",
                (guild.id,),
            )
            update_row = await cur2.fetchone()
            cur3 = await db.execute(
                "SELECT COUNT(*) FROM twitch_streamers WHERE guild_id=?",
                (guild.id,),
            )
            twitch_count = int((await cur3.fetchone())[0] or 0)
        total += 1
        if row and row[0]:
            ch = guild.get_channel(int(row[0]))
            if ch:
                configured += 1
                rows.append(f"✅ ⭐ Starboard → {ch.mention}")
            else:
                rows.append("⚠️ ⭐ Starboard → configured channel was deleted")
        else:
            rows.append(
                f"❌ ⭐ Starboard — set up with {command_mention('mod starboard_setup', fallback='`/mod starboard_setup`')}"
            )
        total += 1
        ch_id = await get_configured_channel_id(guild.id, "complaints_channel_id")
        ch = guild.get_channel(ch_id) if ch_id else None
        if ch_id and ch:
            configured += 1
            rows.append(f"✅ ⚖️ Inheritor docket → {ch.mention}")
        elif ch_id:
            rows.append("⚠️ ⚖️ Inheritor docket → channel missing/deleted")
        else:
            rows.append(
                f"❌ ⚖️ Inheritor docket — {command_mention('general setup_docket', fallback='`/general setup_docket`')}"
            )
        total += 1
        sugg_id = await get_configured_channel_id(guild.id, "suggestions_channel_id")
        sugg_ch = guild.get_channel(sugg_id) if sugg_id else None
        if sugg_id and sugg_ch:
            configured += 1
            rows.append(f"✅ 💡 Suggestions → {sugg_ch.mention}")
        elif sugg_id:
            rows.append("⚠️ 💡 Suggestions → channel missing/deleted")
        else:
            rows.append(
                f"❌ 💡 Suggestions — {command_mention('community suggest_setup', fallback='`/community suggest_setup`')}"
            )
        total += 1
        if update_row and update_row[0]:
            ul_ch = guild.get_channel(int(update_row[0]))
            if ul_ch:
                configured += 1
                rows.append(f"✅ 📝 Update log → {ul_ch.mention}")
            else:
                rows.append("⚠️ 📝 Update log → channel missing/deleted")
        else:
            rows.append(
                f"❌ 📝 Update log — {command_mention('updates update_log_setup', fallback='`/updates update_log_setup`')}"
            )
        total += 1
        if twitch_count > 0:
            configured += 1
            rows.append(f"✅ 📺 Twitch watchlist → **{twitch_count}** streamer(s)")
        else:
            rows.append(
                f"❌ 📺 Twitch watchlist — {command_mention('community twitch_add', fallback='`/community twitch_add`')}"
            )
        return "\n".join(rows)

    core_block = await _channel_section(_CORE_CHECKS)
    wf_block = await _channel_section(_WF_CHECKS)
    mod_block = await _log_section(_MOD_CHECKS)
    extra_block = await _extra_section()
    return configured, total, core_block, wf_block, mod_block, extra_block


async def setup_health_line(guild: discord.Guild) -> str:
    """One-line setup health summary for use in /status and similar commands."""
    configured, total, _c, _w, _m, _e = await compute_setup_health(guild)
    pct = int(100 * configured / total) if total else 0
    icon = "✅" if configured == total else ("⚠️" if configured else "❌")
    return f"{icon} **{configured}/{total}** core features configured ({pct}%)"


async def _build_setup_status_embed(guild: discord.Guild, client) -> discord.Embed:
    configured, total, core_block, wf_block, mod_block, extra_block = await compute_setup_health(guild)
    pct = int(100 * configured / total) if total else 0
    header = f"{render_bar(pct)}  **{configured}/{total}** configured"
    return obsidian_embed(
        "🧭 Server Setup Status",
        header,
        color=EMBED_COLORS.get("general", discord.Color.blue()),
        fields=[
            ("Core", core_block, False),
            ("Warframe feeds", wf_block, False),
            ("Moderation logs", mod_block, False),
            ("Community", extra_block, False),
        ],
        footer="Tip: click a setup command above, then press Refresh to re-check",
        client=client,
    )


class _SetupStatusView(discord.ui.View):
    """Refresh + quick-launch setup wizards."""

    def __init__(self, requester_id: int):
        super().__init__(timeout=300)
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the requester can use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        embed = await _build_setup_status_embed(interaction.guild, interaction.client)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Core setup", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def core_setup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from core.command_mentions import command_mention

        cmd = command_mention("general setup_obsidian", fallback="`/general setup_obsidian`")
        await interaction.response.send_message(
            f"Run {cmd} to configure events, level-up, and voice channels.",
            ephemeral=True,
        )

    @discord.ui.button(label="WF notify", emoji="🔔", style=discord.ButtonStyle.primary)
    async def wf_setup_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from core.command_mentions import command_mention

        cmd = command_mention("wfnotify configure", fallback="`/wfnotify configure`")
        await interaction.response.send_message(
            f"Run {cmd} to set up Warframe alert feeds.",
            ephemeral=True,
        )


def setup(bot, group=None):
    decorator = (
        group.command(name="setup_status", description="See which features are configured vs missing.")
        if group
        else bot.tree.command(name="setup_status", description="See which features are configured vs missing.")
    )

    @decorator
    async def setup_status(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                "Only moderators can view the setup status.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        embed = await _build_setup_status_embed(interaction.guild, interaction.client)
        await interaction.followup.send(
            embed=embed, view=_SetupStatusView(interaction.user.id), ephemeral=True
        )
