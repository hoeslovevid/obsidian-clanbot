"""Suggest channels for Discord’s Community Welcome Screen (administrators)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord  # type: ignore
from discord import app_commands  # type: ignore

from core.utils import obsidian_embed, is_mod


_KEYWORDS = ("announce", "rule", "general", "welcome", "info", "chat", "lfg", "intro", "new")


async def _sample_channel_activity(ch: discord.TextChannel, since: datetime) -> int:
    n = 0
    try:
        async for msg in ch.history(limit=45):
            msg_at = msg.created_at
            if msg_at.tzinfo is None:
                msg_at = msg_at.replace(tzinfo=timezone.utc)
            if msg_at >= since:
                n += 1
            else:
                break
    except Exception:
        return 0
    return n


def setup(bot, group=None) -> None:
    if group is None:
        return

    decorator = group.command(
        name="welcome_recommend",
        description="Suggest channels for the Community Welcome Screen (mods).",
    )

    @decorator
    async def welcome_recommend(interaction: discord.Interaction) -> None:
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

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.me
        if not me:
            return await interaction.followup.send("Bot not ready.", ephemeral=True)

        now = datetime.now(timezone.utc)
        since = now - timedelta(days=7)

        candidates: list[discord.TextChannel] = []
        for ch in guild.text_channels:
            if ch.is_nsfw():
                continue
            if not ch.permissions_for(guild.default_role).view_channel:
                continue
            if not ch.permissions_for(me).read_message_history:
                continue
            candidates.append(ch)
        candidates.sort(key=lambda c: c.position)
        candidates = candidates[:10]

        scored: list[tuple[int, int, int, discord.TextChannel]] = []
        for ch in candidates:
            raw_score = await _sample_channel_activity(ch, since)
            name_bonus = sum(1 for k in _KEYWORDS if k in ch.name.casefold())
            scored.append((raw_score + name_bonus * 3, raw_score, name_bonus, ch))
        scored.sort(key=lambda x: -x[0])

        bullets: list[str] = []
        used: set[int] = set()
        for _, raw_score, nb, ch in scored[:6]:
            parts = []
            if nb:
                parts.append("name matches common onboarding patterns")
            if raw_score > 0:
                parts.append(f"light sample: ~{raw_score} messages in the last 7 days")
            else:
                parts.append("little recent traffic in the sampled history")
            bullets.append(f"• {ch.mention} — {'; '.join(parts)}")
            used.add(ch.id)

        for ch in sorted(guild.text_channels, key=lambda c: c.position):
            if len(bullets) >= 6:
                break
            if ch.id in used or ch.is_nsfw():
                continue
            if not ch.permissions_for(guild.default_role).view_channel:
                continue
            nb = sum(1 for k in _KEYWORDS if k in ch.name.casefold())
            if nb >= 2:
                bullets.append(f"• {ch.mention} — strong name heuristic (rules/info/welcome-style)")
                used.add(ch.id)

        if not bullets:
            bullets.append("• _No strong matches — grant **Read Message History** in key channels and retry._")

        desc = "**Suggested welcome screen channels**\n" + "\n".join(bullets)
        desc += (
            "\n\n**How to apply in Discord**\n"
            "Open **Server Settings → Community → Welcome Screen**, then add these channels with short "
            "descriptions (for example: “Read first”, “Announcements”, “Chat here”). Three to five channels "
            "is usually enough for new members to find their way."
        )

        await interaction.followup.send(
            embed=obsidian_embed(
                "Welcome Screen suggestions",
                desc,
                category="community",
                client=interaction.client,
            ),
            ephemeral=True,
        )
