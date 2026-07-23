"""Ducat vs platinum — should I melt or sell?"""
from __future__ import annotations

import discord
from discord import app_commands

from api.warframe_api import (
    autocomplete_prime_part_names,
    get_warframe_market_price,
    search_warframe_market_item,
)
from core.embed_links import add_link_row, tool_link_button
from core.embed_templates import embed_template
from core.utils import AUTOCOMPLETE_MAX_CHOICES, error_embed
from core.wf_resolve import wf_platform_for


def _verdict(plat: float | None, ducats: int) -> tuple[str, str]:
    if plat is None:
        return "Check the market", "Live sell price unavailable."
    if ducats <= 0:
        return "Sell for platinum", "No ducat value on this item."
    # Community heuristic: melt when plat is very low vs ducats (~<0.1p per ducat).
    if plat < ducats / 10:
        return (
            "Melt for ducats",
            f"{plat:.0f}p for {ducats} ducats is a weak trade — Maroo may be better.",
        )
    return (
        "Sell for platinum",
        f"{plat:.0f}p beats melting {ducats} ducats at current lowest sell.",
    )


async def _item_autocomplete(interaction: discord.Interaction, current: str):
    try:
        matches = await autocomplete_prime_part_names(current, limit=AUTOCOMPLETE_MAX_CHOICES)
    except Exception:
        matches = []
    return [app_commands.Choice(name=m[:100], value=m[:100]) for m in matches]


def setup(bot, group=None):
    cmd = (
        group.command(
            name="ducats",
            description="Should I sell this Prime part for platinum or melt it for ducats?",
        )
        if group
        else bot.tree.command(
            name="ducats",
            description="Should I sell this Prime part for platinum or melt it for ducats?",
        )
    )

    @cmd
    @app_commands.describe(item="Prime part or set name (Warframe Market)")
    @app_commands.autocomplete(item=_item_autocomplete)
    async def ducats(interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        gid = interaction.guild.id if interaction.guild else None
        plat = await wf_platform_for(gid, interaction.user.id)
        found = await search_warframe_market_item(item, platform=plat)
        if not found:
            return await interaction.followup.send(
                embed=error_embed(
                    "Item not found",
                    f"No Warframe Market match for **{item}**. Try a Prime part name.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        name = found.get("item_name") or item
        url_name = found.get("url_name") or ""
        ducat_val = found.get("ducats")
        if ducat_val is None and url_name:
            from api.warframe_api import fetch_wfm_item_detail

            detail = await fetch_wfm_item_detail(url_name, platform=plat)
            if detail:
                ducat_val = detail.get("ducats")
                # v2 detail may nest set members
                if ducat_val is None and isinstance(detail.get("items_in_set"), list):
                    for part in detail["items_in_set"]:
                        if isinstance(part, dict) and (
                            part.get("slug") == url_name or part.get("url_name") == url_name
                        ):
                            ducat_val = part.get("ducats")
                            break
        try:
            ducat_n = int(ducat_val) if ducat_val is not None else 0
        except (TypeError, ValueError):
            ducat_n = 0

        price = await get_warframe_market_price(url_name, platform=plat) if url_name else None
        lowest = price.get("lowest_sell") if price else None
        try:
            lowest_f = float(lowest) if lowest is not None else None
        except (TypeError, ValueError):
            lowest_f = None

        label, detail = _verdict(lowest_f, ducat_n)
        market_url = f"https://warframe.market/items/{url_name}" if url_name else "https://warframe.market/"
        fields = [
            ("Ducats", f"**{ducat_n}**" if ducat_n else "—", True),
            ("Lowest sell", f"**{lowest_f:.0f}p**" if lowest_f is not None else "Unavailable", True),
            ("Verdict", f"**{label}**\n{detail}", False),
        ]
        embed = embed_template(
            "showcase",
            f"💎 Ducats vs Plat · {name}",
            f"[Warframe Market]({market_url})",
            category="warframe",
            fields=fields,
            footer=f"{plat.upper()} · Heuristic only — check live orders before trading",
            client=interaction.client,
        )
        view = discord.ui.View(timeout=120)
        buttons = [
            discord.ui.Button(
                label="Warframe Market",
                url=market_url,
                style=discord.ButtonStyle.link,
                emoji="🛒",
            )
        ]
        site = tool_link_button("Full helper", "worth", emoji="🌐", query=name)
        if site:
            buttons.append(site)
        add_link_row(view, buttons)
        await interaction.followup.send(embed=embed, view=view)
