"""Riven disposition lookup."""
from __future__ import annotations

import discord
from discord import app_commands

from api.warframe_api import autocomplete_weapon_names, search_weapon
from core.embed_links import add_link_row, tool_link_button
from core.embed_templates import embed_template
from core.utils import AUTOCOMPLETE_MAX_CHOICES, error_embed


def _disp_label(disposition) -> str:
    try:
        d = int(disposition)
    except (TypeError, ValueError):
        return "—"
    stars = "★" * max(0, min(5, d)) + "☆" * max(0, 5 - max(0, min(5, d)))
    return f"{d}/5 {stars}"


async def _weapon_autocomplete(interaction: discord.Interaction, current: str):
    try:
        matches = await autocomplete_weapon_names(current, limit=AUTOCOMPLETE_MAX_CHOICES)
    except Exception:
        matches = []
    return [app_commands.Choice(name=m[:100], value=m[:100]) for m in matches]


def setup(bot, group=None):
    cmd = (
        group.command(name="riven", description="Look up a weapon's riven disposition (and ω attenuation).")
        if group
        else bot.tree.command(name="riven", description="Look up a weapon's riven disposition (and ω attenuation).")
    )

    @cmd
    @app_commands.describe(weapon="Weapon name")
    @app_commands.autocomplete(weapon=_weapon_autocomplete)
    async def riven(interaction: discord.Interaction, weapon: str):
        await interaction.response.defer()
        w = await search_weapon(weapon)
        if not w:
            return await interaction.followup.send(
                embed=error_embed(
                    "Weapon not found",
                    f"No match for **{weapon}**. Try another spelling.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        name = str(w.get("name") or weapon)
        wtype = str(w.get("type") or "Weapon")
        disp = w.get("disposition")
        omega = w.get("omegaAttenuation")
        try:
            omega_s = f"{float(omega):.2f}" if omega is not None else "—"
        except (TypeError, ValueError):
            omega_s = "—"

        fields = [
            ("Type", wtype, True),
            ("Disposition", _disp_label(disp), True),
            ("ω Attenuation", omega_s, True),
        ]
        embed = embed_template(
            "showcase",
            f"🎲 Riven · {name}",
            "Higher disposition = stronger riven rolls. Check the site for the full table.",
            category="warframe",
            fields=fields,
            footer="Data from warframestat.us",
            client=interaction.client,
        )
        view = discord.ui.View(timeout=120)
        buttons = []
        for label, tool, emoji in (
            ("Disposition table", "rivens", "🌐"),
            ("Riven grader", "riven-grade", "📊"),
        ):
            btn = tool_link_button(label, tool, emoji=emoji, query=name if tool == "rivens" else None)
            if btn:
                buttons.append(btn)
        add_link_row(view, buttons)
        await interaction.followup.send(embed=embed, view=view)
