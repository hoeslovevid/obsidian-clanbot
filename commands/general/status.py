"""User-facing bot status — version, latency, operational hint."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.config import BOT_VERSION
from core.embed_footers import footer_for
from core.embed_links import LinkRowView, help_link_buttons
from core.embed_templates import embed_template
from core.utils import error_embed
from database import now_utc


async def _warframe_api_hint() -> tuple[str, bool]:
    from core.cache_utils import warframe_health_line

    return warframe_health_line()


def setup(bot, group=None):
    """Register top-level `/status` (not under /general — group is at 25-subcommand cap)."""

    async def status_callback(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Context",
                    "Use this command inside a server.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        latency_ms = round((interaction.client.latency or 0) * 1000)
        api_line, degraded = await _warframe_api_hint()
        try:
            from core.status_history import record_wf_status, wf_status_history_line

            await record_wf_status(degraded, detail=api_line[:120] if degraded else "")
            history = await wf_status_history_line()
        except Exception:
            history = None
        guilds = len(getattr(interaction.client, "guilds", []) or [])
        uptime = "—"
        start = getattr(interaction.client, "start_time", None)
        if start:
            delta = now_utc() - start
            hours, rem = divmod(int(delta.total_seconds()), 3600)
            mins = rem // 60
            uptime = f"{hours}h {mins}m" if hours else f"{mins}m"

        status_title = "⚠️ Obsidian Bot Status" if degraded else "✅ Obsidian Bot Status"
        hint = (
            "_Warframe commands may show cached data until the API recovers. Try again in a minute._"
            if degraded
            else "_If something looks wrong, try again in a minute or ask staff._"
        )

        # Mods also see a one-line setup-health summary (links to /admin setup_status).
        setup_line = ""
        prefs_line = ""
        from core.utils import is_mod
        from database import get_guild_setting
        from core.quiet_hours import parse_quiet_hours

        qh = parse_quiet_hours(
            await get_guild_setting(interaction.guild.id, f"user_quiet_hours:{interaction.user.id}")
        )
        ce = await get_guild_setting(interaction.guild.id, f"user_compact_embeds:{interaction.user.id}") == "1"
        prefs_bits = []
        if qh:
            prefs_bits.append(f"quiet {qh[0]:02d}:00–{qh[1]:02d}:00")
        if ce:
            prefs_bits.append("compact embeds")
        if prefs_bits:
            prefs_line = f"⚙️ Your prefs: {', '.join(prefs_bits)} · `/preferences`"

        if isinstance(interaction.user, discord.Member) and is_mod(interaction.user):
            try:
                from commands.general.setup_status import setup_health_line
                setup_line = await setup_health_line(interaction.guild)
            except Exception:
                setup_line = ""

        from core.maintenance import maintenance_enabled, maintenance_message

        maint_line = ""
        if maintenance_enabled():
            maint_line = f"\n🔧 **Maintenance:** {maintenance_message()}\n"

        body = (
            f"**Version:** `{BOT_VERSION}`\n"
            f"**Gateway:** {latency_ms} ms · **Uptime:** {uptime}\n"
            f"**Servers:** {guilds}\n"
            f"{maint_line}\n"
            f"{api_line}\n"
            + (f"{history}\n" if history else "")
            + (f"🧭 {setup_line}\n" if setup_line else "")
            + (f"{prefs_line}\n" if prefs_line else "")
            + f"\n{hint}"
        )
        embed = embed_template(
            "showcase",
            status_title,
            body,
            category="warning" if degraded else "general",
            footer=footer_for("status", version=BOT_VERSION),
            client=interaction.client,
        )
        view = LinkRowView(*help_link_buttons())
        from core.help_layout import help_layout_v2_enabled
        from core.status_layout import StatusLayout

        if help_layout_v2_enabled():
            try:
                layout = StatusLayout(
                    title=status_title.replace("✅ ", "").replace("⚠️ ", ""),
                    body=body,
                    version=BOT_VERSION,
                    degraded=degraded,
                )
                await interaction.followup.send(view=layout, ephemeral=True)
                return
            except Exception:
                pass
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    if group is not None:
        group.command(name="status", description="Bot version, latency, and service health.")(status_callback)
    else:
        bot.tree.add_command(
            app_commands.Command(
                name="status",
                description="Bot version, latency, and service health.",
                callback=status_callback,
            )
        )
