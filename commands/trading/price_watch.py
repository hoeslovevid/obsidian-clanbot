"""Market price watch — DM when an item drops below your target."""
from __future__ import annotations

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.price_watchlist import add_watch, list_watches, remove_watch
from core.utils import obsidian_embed, success_embed, error_embed, EMBED_COLORS
from commands.trading.trade_price import item_autocomplete


def setup(bot, group=None):
    group = None

    @bot.tree.command(name="price_watch", description="DM me when a Warframe Market item drops to my target price.")
    @app_commands.describe(item="Item name", max_price="Notify when lowest sell is at or below this (platinum)")
    @app_commands.autocomplete(item=item_autocomplete)
    async def price_watch(interaction: discord.Interaction, item: str, max_price: app_commands.Range[int, 1, 999999]):
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        from database import get_user_platform

        platform = await get_user_platform(interaction.guild.id, interaction.user.id) or "pc"
        ok, msg = await add_watch(interaction.guild.id, interaction.user.id, item, int(max_price), platform)
        if ok:
            body = msg
            from core.first_run_nudge import maybe_first_run_hint
            body = await maybe_first_run_hint(
                interaction.guild.id, interaction.user.id, body, feature="price_watch"
            )
            return await interaction.response.send_message(
                embed=success_embed("Price watch set", body, client=interaction.client),
                ephemeral=True,
            )
        return await interaction.response.send_message(
            embed=error_embed("Could not add watch", msg, client=interaction.client),
            ephemeral=True,
        )

    @bot.tree.command(name="price_unwatch", description="Remove a market price watch.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def price_unwatch(interaction: discord.Interaction, item: str):
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        ok, msg = await remove_watch(interaction.guild.id, interaction.user.id, item)
        if ok:
            return await interaction.response.send_message(
                embed=success_embed("Removed", msg, client=interaction.client),
                ephemeral=True,
            )
        return await interaction.response.send_message(
            embed=error_embed("Not found", msg, client=interaction.client),
            ephemeral=True,
        )

    @bot.tree.command(name="price_watches", description="List your active market price watches.")
    async def price_watches(interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        rows = await list_watches(interaction.guild.id, interaction.user.id)
        if not rows:
            return await interaction.response.send_message(
                embed=embed_template(
                    "showcase",
                    "💎 Price watches",
                    "You're not watching any items yet.\n\n"
                    "Use **`/price_watch`** with an item and max platinum — "
                    "I'll DM you when sellers hit your target.",
                    category="trading",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
        lines = [f"• **{name}** — ≤{cap}p ({plat.upper()})" for name, cap, plat in rows]
        await interaction.response.send_message(
            embed=obsidian_embed(
                "💎 Your price watches",
                "\n".join(lines),
                color=EMBED_COLORS.get("economy", discord.Color.gold()),
                footer="Checked every ~30 minutes",
                client=interaction.client,
            ),
            ephemeral=True,
        )
