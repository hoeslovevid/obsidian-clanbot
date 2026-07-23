"""Prime Vault / Varzia lookup."""
from __future__ import annotations

import re

import dateparser
import discord
from discord import app_commands

from api.warframe_api import fetch_vault_trader, fetch_warframes
from core.embed_links import add_link_row, tool_link_button
from core.embed_templates import embed_template
from core.utils import error_embed, warframe_data_unavailable_embed
from core.wf_resolve import wf_platform_for


def _fmt_expiry(expiry_str: str) -> str:
    try:
        exp = dateparser.parse(
            expiry_str,
            settings={"TIMEZONE": "UTC", "RETURN_AS_TIMEZONE_AWARE": True},
        )
        if not exp:
            return expiry_str or "?"
        return f"<t:{int(exp.timestamp())}:R>"
    except Exception:
        return expiry_str or "?"


def _aya_label(entry: dict) -> str:
    name = str(entry.get("item") or "")
    path = str(entry.get("uniqueName") or "")
    is_regal = bool(
        re.search(r"Pack|MPV|MegaPrimeVault", name, re.I)
        or re.search(r"Pack|MegaPrimeVault|MPV", path, re.I)
    )
    if entry.get("ducats") is not None:
        unit = "Regal Aya" if is_regal else "Aya"
        return f"{entry['ducats']} {unit}"
    if entry.get("credits") is not None:
        return f"{entry['credits']} credits"
    return "—"


def setup(bot, group=None):
    cmd = (
        group.command(
            name="vault",
            description="Check if a Prime is vaulted, or browse Varzia's current inventory.",
        )
        if group
        else bot.tree.command(
            name="vault",
            description="Check if a Prime is vaulted, or browse Varzia's current inventory.",
        )
    )

    @cmd
    @app_commands.describe(prime="Optional Prime warframe name (e.g. Mesa Prime). Leave empty for Varzia.")
    async def vault(interaction: discord.Interaction, prime: str | None = None):
        await interaction.response.defer()
        gid = interaction.guild.id if interaction.guild else None
        plat = await wf_platform_for(gid, interaction.user.id)

        frames = await fetch_warframes()
        trader = await fetch_vault_trader(plat)

        if frames is None and trader is None:
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )

        fields = []
        title = "🏛️ Prime Vault"
        desc = "Vaulted Primes and Varzia (Prime Resurgence)."

        q = (prime or "").strip()
        if q:
            q_lower = q.lower()
            q_lower_prime = q_lower if q_lower.endswith("prime") else q_lower + " prime"
            match = None
            for wf in frames or []:
                if not isinstance(wf, dict):
                    continue
                name = str(wf.get("name") or "")
                nl = name.lower()
                if nl == q_lower or nl == q_lower_prime or q_lower in nl:
                    match = wf
                    if nl == q_lower or nl == q_lower_prime:
                        break
            if not match:
                return await interaction.followup.send(
                    embed=error_embed(
                        "Not found",
                        f"No warframe matched **{q}**. Try `Mesa Prime` or leave blank for Varzia.",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            name = str(match.get("name") or q)
            vaulted = bool(match.get("vaulted"))
            title = f"🏛️ {name}"
            desc = (
                "Currently **vaulted** — farm via relics/Varzia when available."
                if vaulted
                else "Currently **unvaulted** — available from relics."
            )
            fields.append(("Status", "🔒 Vaulted" if vaulted else "✅ Unvaulted", True))

        vaulted_frames = [wf for wf in (frames or []) if isinstance(wf, dict) and wf.get("vaulted")]
        if not q:
            fields.append(("Vaulted warframes", str(len(vaulted_frames)), True))
            sample = sorted(vaulted_frames, key=lambda w: str(w.get("name") or ""))[:12]
            if sample:
                lines = [f"• {w.get('name')}" for w in sample]
                more = len(vaulted_frames) - len(sample)
                if more > 0:
                    lines.append(f"_…and {more} more_")
                fields.append(("Examples", "\n".join(lines), False))

        if trader and isinstance(trader, dict):
            who = trader.get("character") or "Varzia"
            loc = trader.get("location") or "?"
            exp = _fmt_expiry(str(trader.get("expiry") or ""))
            inv = trader.get("inventory") or []
            fields.append(("Vault trader", f"**{who}** · {loc}\nExpires: {exp}", False))
            if isinstance(inv, list) and inv:
                lines = []
                for entry in inv[:10]:
                    if not isinstance(entry, dict):
                        continue
                    lines.append(f"• {entry.get('item', '?')} — {_aya_label(entry)}")
                if len(inv) > 10:
                    lines.append(f"_…+{len(inv) - 10} more_")
                fields.append(("Inventory", "\n".join(lines)[:1020], False))

        embed = embed_template(
            "showcase",
            title,
            desc,
            category="warframe",
            fields=fields or [("Info", "No vault data.", False)],
            footer=f"{plat.upper()} · Full list on the website",
            client=interaction.client,
        )
        view = discord.ui.View(timeout=120)
        buttons = []
        btn = tool_link_button("Prime vault", "vault", emoji="🌐", query=q or None)
        if btn:
            buttons.append(btn)
        if q:
            worth = tool_link_button("Ducat / plat", "worth", emoji="💎", query=q)
            if worth:
                buttons.append(worth)
        add_link_row(view, buttons)
        await interaction.followup.send(embed=embed, view=view)
