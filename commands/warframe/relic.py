"""Void relic contents lookup."""
from __future__ import annotations

import discord
from discord import app_commands

from api.warframe_api import fetch_items_search
from core.embed_links import add_link_row, tool_link_button
from core.embed_templates import embed_template
from core.utils import error_embed, warframe_data_unavailable_embed


def _relic_tier(name: str) -> str:
    import re

    m = re.match(r"^(Lith|Meso|Neo|Axi|Requiem|Omnia)\b", name or "", re.I)
    if not m:
        return ""
    return m.group(1).capitalize() if m.group(1).lower() != "omnia" else "Omnia"


def _format_rewards(rewards) -> str:
    if not isinstance(rewards, list) or not rewards:
        return "_No rewards listed._"
    lines = []
    for r in rewards[:12]:
        if not isinstance(r, dict):
            continue
        item = r.get("itemName") or r.get("name") or "?"
        chance = r.get("chance")
        rarity = r.get("rarity") or ""
        extra = []
        if rarity:
            extra.append(str(rarity))
        if chance is not None:
            try:
                extra.append(f"{float(chance):.1f}%")
            except (TypeError, ValueError):
                pass
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"• {item}{suffix}")
    return "\n".join(lines) if lines else "_No rewards listed._"


def setup(bot, group=None):
    cmd = (
        group.command(name="relic", description="Look up a Void relic's rewards and vaulted status.")
        if group
        else bot.tree.command(name="relic", description="Look up a Void relic's rewards and vaulted status.")
    )

    @cmd
    @app_commands.describe(name="Relic name, e.g. Neo A1 or Lith G1")
    async def relic(interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        q = (name or "").strip()
        if len(q) < 2:
            return await interaction.followup.send(
                embed=error_embed("Too short", "Enter a relic name like `Neo A1`.", client=interaction.client),
                ephemeral=True,
            )

        results = await fetch_items_search(q)
        if results is None:
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )

        relics = [
            it
            for it in results
            if isinstance(it, dict)
            and it.get("type") == "Relic"
            and "Intact" in str(it.get("name") or "")
        ]
        if not relics:
            # Fallback: any Relic type
            relics = [it for it in results if isinstance(it, dict) and it.get("type") == "Relic"]

        if not relics:
            return await interaction.followup.send(
                embed=error_embed(
                    "No relics found",
                    f"Nothing matched **{q}**. Try a tier + letter (e.g. `Axi S8`).",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Prefer exact-ish match on base name
        q_lower = q.lower()
        relics.sort(
            key=lambda it: (
                0 if q_lower in str(it.get("name") or "").lower() else 1,
                len(str(it.get("name") or "")),
            )
        )
        primary = relics[0]
        base = str(primary.get("name") or q).replace(" Intact", "").strip()
        tier = _relic_tier(base) or str(primary.get("tier") or "?")
        vaulted = bool(primary.get("vaulted"))
        fields = [
            ("Tier", tier, True),
            ("Status", "🔒 Vaulted" if vaulted else "✅ Unvaulted", True),
            ("Rewards (Intact)", _format_rewards(primary.get("rewards")), False),
        ]
        extras = relics[1:4]
        if extras:
            more = ", ".join(str(r.get("name") or "?").replace(" Intact", "") for r in extras)
            fields.append(("Also matched", more[:1020], False))

        embed = embed_template(
            "showcase",
            f"🗿 Relic · {base}",
            "Intact rewards from warframestat.us.",
            category="warframe",
            fields=fields,
            footer="See also: /warframe fissures · /wftools vault",
            client=interaction.client,
        )
        view = discord.ui.View(timeout=120)
        buttons = []
        for label, tool, emoji in (
            ("Relic browser", "relics", "🌐"),
            ("Planner", "planner", "🗺️"),
            ("Live world state", "warframe", "📡"),
        ):
            btn = tool_link_button(label, tool, emoji=emoji, query=base if tool == "relics" else None)
            if btn:
                buttons.append(btn)
        add_link_row(view, buttons)
        await interaction.followup.send(embed=embed, view=view)
