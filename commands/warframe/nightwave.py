"""Dedicated Nightwave challenges command."""
from __future__ import annotations

import discord

from api.warframe_api import fetch_nightwave
from core.embed_links import LinkRowView, nightwave_link_buttons
from core.embed_templates import embed_template
from core.utils import warframe_data_unavailable_embed
from core.wf_copy import merge_wf_footer
from core.wf_resolve import wf_fetch_failed, wf_platform_for


def _challenge_title(c: dict) -> str:
    return str(c.get("title") or c.get("desc") or str(c)[:60])


def _split_challenges(nw: dict) -> tuple[list, list]:
    daily = nw.get("dailyChallenges") or []
    weekly = nw.get("weeklyChallenges") or []
    if (not daily and not weekly) and nw.get("activeChallenges"):
        ac = nw["activeChallenges"]
        if isinstance(ac, list):
            daily = [c for c in ac if c.get("isDaily")]
            weekly = [c for c in ac if not c.get("isDaily")]
    return (
        daily if isinstance(daily, list) else [],
        weekly if isinstance(weekly, list) else [],
    )


def _build_embed(nw: dict, client, *, platform: str = "pc") -> discord.Embed:
    season = nw.get("season", nw.get("seasonTag", "?"))
    daily, weekly = _split_challenges(nw)
    fields = []
    if daily:
        lines = [f"• {_challenge_title(c)}" for c in daily[:10]]
        fields.append(("Daily", "\n".join(lines), False))
    if weekly:
        lines = [f"• {_challenge_title(c)}" for c in weekly[:12]]
        fields.append(("Weekly", "\n".join(lines), False))
    if not fields:
        fields.append(("Challenges", "No active challenges listed.", False))
    footer = merge_wf_footer(
        f"{platform.upper()} · See also: /warframe daily_ops",
        f"warframe:nightwave:{platform}",
    )
    return embed_template(
        "showcase",
        f"🌙 Nightwave · Season {season}",
        "Current Nora's Choice challenges. Use the site checklist to track progress.",
        category="warframe",
        fields=fields,
        footer=footer,
        client=client,
    )


def setup(bot, group=None):
    cmd = (
        group.command(name="nightwave", description="Current Nightwave daily and weekly challenges.")
        if group
        else bot.tree.command(name="nightwave", description="Current Nightwave daily and weekly challenges.")
    )

    @cmd
    async def nightwave(interaction: discord.Interaction):
        await interaction.response.defer()
        gid = interaction.guild.id if interaction.guild else None
        plat = await wf_platform_for(gid, interaction.user.id)
        nw = await fetch_nightwave(plat)
        if wf_fetch_failed(nw):
            return await interaction.followup.send(
                embed=warframe_data_unavailable_embed(interaction.client),
                ephemeral=True,
            )
        embed = _build_embed(nw, interaction.client, platform=plat)
        view = LinkRowView(*nightwave_link_buttons())
        await interaction.followup.send(embed=embed, view=view)
