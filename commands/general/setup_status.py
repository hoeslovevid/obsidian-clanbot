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

        from core.command_mentions import command_mention

        guild = interaction.guild
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

        pct = int(100 * configured / total) if total else 0
        header = f"{render_bar(pct)}  **{configured}/{total}** configured"

        embed = obsidian_embed(
            "🧭 Server Setup Status",
            header,
            color=EMBED_COLORS.get("general", discord.Color.blue()),
            fields=[
                ("Core", core_block, False),
                ("Warframe feeds", wf_block, False),
            ],
            footer="Tip: click a setup command above to configure a missing feature",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
