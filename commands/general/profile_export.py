"""Export personal profile stats as text (privacy / transparency)."""
from __future__ import annotations

import io
import json

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.utils import error_embed
from commands.general.profile import get_user_profile_data


def setup(bot, group=None):
    group = None

    @bot.tree.command(
        name="profile_export",
        description="Download your profile stats as JSON (coins, XP, activity).",
    )
    async def profile_export(interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        await interaction.response.defer(ephemeral=True)
        data = await get_user_profile_data(interaction.guild.id, interaction.user.id)
        export = {
            "guild_id": interaction.guild.id,
            "user_id": interaction.user.id,
            "balance": data.get("balance"),
            "total_earned": data.get("total_earned"),
            "xp": data.get("xp"),
            "level": data.get("level"),
            "messages_sent": data.get("messages_sent"),
            "voice_minutes": data.get("voice_minutes"),
            "daily_streak": data.get("daily_streak"),
            "events_attended": data.get("events_attended"),
        }
        body = json.dumps(export, indent=2)
        fp = io.BytesIO(body.encode("utf-8"))
        fp.seek(0)
        await interaction.followup.send(
            embed=embed_template(
                "showcase",
                "📤 Profile export",
                "Your personal stats for this server (not shared publicly).",
                category="general",
                client=interaction.client,
            ),
            file=discord.File(fp, filename=f"profile-{interaction.guild.id}.json"),
            ephemeral=True,
        )
