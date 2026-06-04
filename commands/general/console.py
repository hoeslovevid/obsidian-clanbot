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


class ConsoleHubView(discord.ui.View):
    """Persistent hub buttons — registered on startup for pinned console messages."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _hint(self, interaction: discord.Interaction, command: str, detail: str):
        await interaction.response.send_message(
            f"Run **`{command}`** — {detail}",
            ephemeral=True,
        )

    @discord.ui.button(label="Menu", style=discord.ButtonStyle.primary, emoji="📋", custom_id="obsidian_console:menu")
    async def menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hint(interaction, "/menu", "categorized command picker.")

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.secondary, emoji="🎁", custom_id="obsidian_console:daily")
    async def daily_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hint(interaction, "/daily", "claim your daily coin streak.")

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, emoji="🎮", custom_id="obsidian_console:status")
    async def wf_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hint(interaction, "/warframe status", "Baro, alerts, and cycles.")

    @discord.ui.button(label="Ticket", style=discord.ButtonStyle.secondary, emoji="🎫", custom_id="obsidian_console:ticket")
    async def ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hint(interaction, "/ticket", "open a support ticket.")

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="❓", custom_id="obsidian_console:help")
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._hint(interaction, "/help", "searchable command reference.")


def _hub_embed(client) -> discord.Embed:
    return embed_template(
        "showcase",
        "🜂 Obsidian Clan Console",
        (
            "Your command center for daily rewards, Warframe intel, support tickets, and help.\n\n"
            "**Quick picks** — use the buttons below or slash commands:\n"
            "• **`/menu`** — categorized command picker\n"
            "• **`/daily`** — claim your coin streak\n"
            "• **`/warframe status`** — Baro, alerts, cycles\n"
            "• **`/ticket`** — open a support ticket\n"
            "• **`/help`** — full command reference"
        ),
        category="general",
        footer=footer_for("console_hub"),
        client=client,
        brand=True,
    )


def setup(bot, group=None):
    """Register `/general console` (mods post a pinned hub)."""

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

        embed = _hub_embed(interaction.client)
        view = ConsoleHubView()
        msg = await target.send(embed=embed, view=view)
        # Optional website row as a second message is noisy; help links live in embed footer.
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
