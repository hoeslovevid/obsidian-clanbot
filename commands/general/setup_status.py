"""/admin setup_status — at-a-glance view of configured vs missing features."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, EMBED_COLORS, is_mod, render_bar
from database import get_configured_channel_id

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


async def compute_setup_health(guild: discord.Guild) -> tuple[int, int, str, str]:
    """Return (configured, total, core_block, wf_block) for the guild's setup."""
    from core.command_mentions import command_mention

    configured = 0
    total = 0

    async def _section(checks):
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

    core_block = await _section(_CORE_CHECKS)
    wf_block = await _section(_WF_CHECKS)
    return configured, total, core_block, wf_block


async def setup_health_line(guild: discord.Guild) -> str:
    """One-line setup health summary for use in /status and similar commands."""
    configured, total, _core, _wf = await compute_setup_health(guild)
    pct = int(100 * configured / total) if total else 0
    icon = "✅" if configured == total else ("⚠️" if configured else "❌")
    return f"{icon} **{configured}/{total}** core features configured ({pct}%)"


async def _build_setup_status_embed(guild: discord.Guild, client) -> discord.Embed:
    configured, total, core_block, wf_block = await compute_setup_health(guild)
    pct = int(100 * configured / total) if total else 0
    header = f"{render_bar(pct)}  **{configured}/{total}** configured"
    return obsidian_embed(
        "🧭 Server Setup Status",
        header,
        color=EMBED_COLORS.get("general", discord.Color.blue()),
        fields=[
            ("Core", core_block, False),
            ("Warframe feeds", wf_block, False),
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
