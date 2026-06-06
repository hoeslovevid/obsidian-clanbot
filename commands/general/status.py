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
        embed = embed_template(
            "showcase",
            status_title,
            (
                f"**Version:** `{BOT_VERSION}`\n"
                f"**Gateway:** {latency_ms} ms · **Uptime:** {uptime}\n"
                f"**Servers:** {guilds}\n\n"
                f"{api_line}\n\n"
                f"{hint}"
            ),
            category="warning" if degraded else "general",
            footer=footer_for("status", version=BOT_VERSION),
            client=interaction.client,
        )
        view = LinkRowView(*help_link_buttons())
        from core.help_layout import help_layout_v2_enabled
        from core.status_layout import StatusLayout

        if help_layout_v2_enabled():
            try:
                body = (
                    f"**Version:** `{BOT_VERSION}`\n"
                    f"**Gateway:** {latency_ms} ms · **Uptime:** {uptime}\n"
                    f"**Servers:** {guilds}\n\n"
                    f"{api_line}\n\n"
                    f"{hint}"
                )
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
