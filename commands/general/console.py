"""Clan Console — pinned hub with quick links (voice panel / configured channel)."""
from __future__ import annotations

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.channels import resolve_channel_id
from core.config import VOICE_PANEL_CHANNEL_ID, VOICE_PANEL_CHANNEL_NAME
from core.embed_templates import embed_template
from core.embed_footers import footer_for
from core.utils import error_embed, is_mod, success_embed
from database import set_guild_setting

# Stateless buttons — routed only via handlers/component_handler.py (no view callbacks).
_CONSOLE_HUB_BUTTONS: tuple[tuple[str, str, discord.ButtonStyle, str], ...] = (
    ("Menu", "📋", discord.ButtonStyle.primary, "menu"),
    ("Daily", "🎁", discord.ButtonStyle.secondary, "daily"),
    ("Status", "✅", discord.ButtonStyle.secondary, "status"),
    ("Ticket", "🎫", discord.ButtonStyle.secondary, "ticket"),
    ("Help", "❓", discord.ButtonStyle.secondary, "help"),
)


class ConsoleHubView(discord.ui.View):
    """Persistent hub shell — custom_ids only; hints handled in component_handler."""

    def __init__(self):
        super().__init__(timeout=None)
        for label, emoji, style, action in _CONSOLE_HUB_BUTTONS:
            self.add_item(
                discord.ui.Button(
                    label=label,
                    style=style,
                    emoji=emoji,
                    custom_id=f"obsidian_console:{action}",
                )
            )


def _hub_embed(client, guild: discord.Guild | None = None) -> discord.Embed:
    body = (
        "Your command center for daily rewards, Warframe intel, support tickets, and help.\n\n"
        "**Quick picks** — use the buttons below or slash commands:\n"
        "• **`/menu`** — categorized command picker\n"
        "• **`/daily`** — claim your coin streak\n"
        "• **`/status`** — bot version, latency, Warframe API health\n"
        "• **`/warframe status`** — Baro, alerts, cycles\n"
        "• **`/ticket`** — open a support ticket\n"
        "• **`/help`** — full command reference\n"
        "• **`/favorite_add`** — pin commands; they show in `/menu` and `/help`"
    )
    try:
        from core.command_sync import sync_scope_description
        from core.config import BOT_VERSION

        body += f"\n\n-# **v{BOT_VERSION}** · {sync_scope_description()} · staff: `/admin health`"
    except Exception:
        pass
    if guild:
        try:
            from core.music_player import format_music_console_block

            music_block = format_music_console_block(guild)
            if music_block:
                body += f"\n\n{music_block}"
        except Exception:
            pass
    return embed_template(
        "showcase",
        "🜂 Obsidian Clan Console",
        body,
        category="general",
        footer=footer_for("console_hub"),
        client=client,
        brand=True,
    )


def setup(bot, group=None):
    """Register `/admin console` (mods post a pinned hub)."""

    @group.command(
        name="console",
        description="Post the pinned Clan Console hub (Menu, Daily, Status, Ticket, Help).",
    )
    @app_commands.describe(channel="Channel to post in (default: voice panel / obsidian-console)")
    async def console_cmd(
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Context",
                    "This command can only be used inside a server.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed(
                    "Permission Denied",
                    "Only server administrators can post the Clan Console hub.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        target = channel
        if target is None:
            ch_id = await resolve_channel_id(
                interaction.guild,
                "voice_panel_channel_id",
                VOICE_PANEL_CHANNEL_ID,
                VOICE_PANEL_CHANNEL_NAME,
            )
            if ch_id:
                ch = interaction.guild.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    target = ch
        if target is None:
            return await interaction.response.send_message(
                embed=error_embed(
                    "No Channel",
                    "Pick a channel, or run `/general setup_obsidian` to configure the voice panel channel.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        me = interaction.guild.me
        if not me or not target.permissions_for(me).send_messages:
            return await interaction.response.send_message(
                embed=error_embed(
                    "Missing Permissions",
                    f"I need **Send Messages** and **Embed Links** in {target.mention}.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        embed = _hub_embed(interaction.client, interaction.guild)
        from core.console_layout import ConsoleHubLayout
        from core.help_layout import help_layout_v2_enabled

        if help_layout_v2_enabled():
            try:
                layout = ConsoleHubLayout(body=embed.description or "")
                msg = await target.send(view=layout)
            except Exception:
                view = ConsoleHubView()
                msg = await target.send(embed=embed, view=view)
        else:
            view = ConsoleHubView()
            msg = await target.send(embed=embed, view=view)
        try:
            await msg.pin(reason="Obsidian Clan Console hub")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await set_guild_setting(interaction.guild.id, "console_hub_message_id", str(msg.id))
        await set_guild_setting(interaction.guild.id, "console_hub_channel_id", str(target.id))

        await interaction.response.send_message(
            embed=success_embed(
                "Console Posted",
                f"Pinned hub in {target.mention}. Members can use the link buttons anytime.",
                client=interaction.client,
            ),
            ephemeral=True,
        )