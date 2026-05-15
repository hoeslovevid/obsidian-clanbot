"""Configure phishing heuristics (flag-only: reaction, optional DM, optional mod log)."""
from __future__ import annotations

import json
from typing import Optional

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.phishing_scanner import normalize_domain
from core.utils import obsidian_embed, success_embed, is_mod
from database import delete_guild_setting, get_guild_setting, set_guild_setting


def setup(bot, group=None) -> None:
    if group is None:
        return

    phishing = app_commands.Group(
        name="phishing",
        description="Flag suspicious links (reaction + log; never deletes messages).",
    )

    @phishing.command(name="enable", description="Turn phishing heuristics on or off for this server.")
    @app_commands.describe(enabled="When true, new messages are scanned for scam patterns")
    async def phishing_enable(interaction: discord.Interaction, enabled: bool) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_mod(interaction.user):
            embed = obsidian_embed(
                "Permission denied",
                "Administrator permission required.",
                category="error",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await set_guild_setting(interaction.guild.id, "phishing_enabled", "1" if enabled else "0")
        embed = success_embed(
            "Phishing scan",
            "Enabled — suspicious messages get a warning reaction and optional log entry."
            if enabled
            else "Disabled — no phishing scanning on new messages.",
            client=interaction.client,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @phishing.command(name="log_channel", description="Channel for phishing alert embeds (omit to clear).")
    @app_commands.describe(channel="Text channel for mod-visible alerts")
    async def phishing_log_channel(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_mod(interaction.user):
            embed = obsidian_embed(
                "Permission denied",
                "Administrator permission required.",
                category="error",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if channel is None:
            await delete_guild_setting(interaction.guild.id, "phishing_log_channel_id")
            msg = "Cleared the phishing log channel."
        else:
            await set_guild_setting(interaction.guild.id, "phishing_log_channel_id", str(channel.id))
            msg = f"Phishing hits will be posted to {channel.mention}."

        await interaction.response.send_message(
            embed=success_embed("Phishing log", msg, client=interaction.client),
            ephemeral=True,
        )

    allowlist = app_commands.Group(name="allowlist", description="Trusted hostnames (URLs using only these may be skipped)")

    async def _load_allow(interaction: discord.Interaction) -> list[str]:
        raw = await get_guild_setting(interaction.guild.id, "phishing_allowlist") or ""
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            return [p.strip() for p in raw.split(",") if p.strip()]
        return []

    @allowlist.command(name="add", description="Allowlist a domain (hostname only, e.g. steamcommunity.com)")
    @app_commands.describe(domain="Domain to trust for URL allowlisting")
    async def allowlist_add(interaction: discord.Interaction, domain: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_mod(interaction.user):
            embed = obsidian_embed(
                "Permission denied",
                "Administrator permission required.",
                category="error",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        norm = normalize_domain(domain)
        if not norm:
            return await interaction.response.send_message(
                embed=obsidian_embed("Invalid domain", "Provide a hostname such as `steamcommunity.com`.", category="error", client=interaction.client),
                ephemeral=True,
            )
        cur = await _load_allow(interaction)
        as_set = {normalize_domain(x) for x in cur if normalize_domain(x)}
        as_set.add(norm)
        ordered = sorted(as_set)
        await set_guild_setting(interaction.guild.id, "phishing_allowlist", json.dumps(ordered))
        await interaction.response.send_message(
            embed=success_embed("Allowlist", f"Added `{norm}`. Total: **{len(ordered)}** domains.", client=interaction.client),
            ephemeral=True,
        )

    @allowlist.command(name="remove", description="Remove a domain from the allowlist")
    @app_commands.describe(domain="Hostname to remove")
    async def allowlist_remove(interaction: discord.Interaction, domain: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_mod(interaction.user):
            embed = obsidian_embed(
                "Permission denied",
                "Administrator permission required.",
                category="error",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        norm = normalize_domain(domain)
        cur = await _load_allow(interaction)
        as_set = {normalize_domain(x) for x in cur if normalize_domain(x)}
        if norm not in as_set:
            return await interaction.response.send_message(
                embed=obsidian_embed("Not found", f"`{norm}` is not on the allowlist.", category="warning", client=interaction.client),
                ephemeral=True,
            )
        as_set.remove(norm)
        ordered = sorted(as_set)
        if ordered:
            await set_guild_setting(interaction.guild.id, "phishing_allowlist", json.dumps(ordered))
        else:
            await delete_guild_setting(interaction.guild.id, "phishing_allowlist")
        await interaction.response.send_message(
            embed=success_embed("Allowlist", f"Removed `{norm}`.", client=interaction.client),
            ephemeral=True,
        )

    @allowlist.command(name="list", description="Show allowlisted domains")
    async def allowlist_list(interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if not is_mod(interaction.user):
            embed = obsidian_embed(
                "Permission denied",
                "Administrator permission required.",
                category="error",
                client=interaction.client,
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        cur = await _load_allow(interaction)
        normed = sorted({normalize_domain(x) for x in cur if normalize_domain(x)})
        if not normed:
            body = "_No domains allowlisted yet._"
        else:
            body = "\n".join(f"• `{d}`" for d in normed)
        await interaction.response.send_message(
            embed=obsidian_embed("Phishing allowlist", body, category="general", client=interaction.client),
            ephemeral=True,
        )

    phishing.add_command(allowlist)
    group.add_command(phishing)
