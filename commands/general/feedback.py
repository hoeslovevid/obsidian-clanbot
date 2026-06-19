"""Member feedback — report issues or suggestions to staff."""
from __future__ import annotations

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.utils import error_embed, success_embed
from database import get_guild_setting, now_utc


class FeedbackModal(discord.ui.Modal, title="Send feedback"):
    def __init__(self, *, error_code: str | None = None):
        super().__init__()
        self._error_code = error_code
        default_msg = ""
        if error_code:
            default_msg = (
                f"Error code: {error_code}\n\n"
                "(Describe what you were doing when this happened.)"
            )
        self.message = discord.ui.TextInput(
            label="Your message",
            style=discord.TextStyle.paragraph,
            placeholder="Bug report, idea, or praise — include steps to reproduce if it's a bug.",
            required=True,
            max_length=1500,
            default=default_msg or None,
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=error_embed("Server only", "Use this inside a server.", client=interaction.client),
                ephemeral=True,
            )
        text = (self.message.value or "").strip()
        if self._error_code and self._error_code not in text:
            text = f"Error code: {self._error_code}\n\n{text}"
        ch_raw = await get_guild_setting(interaction.guild.id, "feedback_channel_id")
        staff_embed = embed_template(
            "showcase",
            "💬 Member feedback",
            text,
            category="community",
            fields=[
                ("From", interaction.user.mention, True),
                ("Channel", interaction.channel.mention if interaction.channel else "—", True),
            ],
            footer=f"Guild {interaction.guild.id} · {now_utc().isoformat()[:19]}",
            client=interaction.client,
        )
        delivered = False
        if ch_raw and str(ch_raw).strip().isdigit():
            ch = interaction.guild.get_channel(int(ch_raw))
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=staff_embed)
                    delivered = True
                except Exception:
                    pass
        if not delivered:
            mod_role_raw = await get_guild_setting(interaction.guild.id, "mod_role_id")
            if mod_role_raw and str(mod_role_raw).strip().isdigit():
                role = interaction.guild.get_role(int(mod_role_raw))
                if role and interaction.channel and isinstance(interaction.channel, discord.TextChannel):
                    try:
                        await interaction.channel.send(
                            content=role.mention,
                            embed=staff_embed,
                            allowed_mentions=discord.AllowedMentions(roles=True),
                        )
                        delivered = True
                    except Exception:
                        pass
        await interaction.response.send_message(
            embed=success_embed(
                "Thanks for the feedback",
                "Staff received your message."
                if delivered
                else "Couldn't reach a feedback channel — ask staff to run `/admin feedback_setup`.",
                client=interaction.client,
            ),
            ephemeral=True,
        )


def setup(bot, group=None):
    @bot.tree.command(
        name="feedback",
        description="Send feedback or report a bot issue to staff (private).",
    )
    async def feedback_cmd(interaction: discord.Interaction):
        if not interaction.guild:
            from core.reply_helpers import reply_server_only
            return await reply_server_only(interaction)
        await interaction.response.send_modal(FeedbackModal())
