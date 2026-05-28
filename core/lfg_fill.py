"""Shared LFG mark-as-filled logic (channel panel + DM button)."""
from __future__ import annotations

from typing import Optional

import aiosqlite  # type: ignore
import discord  # type: ignore

from database import DB_PATH


async def mark_lfg_filled(
    lfg_id: int,
    user_id: int,
    *,
    client: discord.Client,
    guild: Optional[discord.Guild] = None,
) -> tuple[bool, str]:
    """Mark an LFG post filled. Returns (success, user-facing message)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT creator_id, status, channel_id, message_id, guild_id FROM lfg_posts WHERE id=?",
            (lfg_id,),
        )
        post = await cur.fetchone()

    if not post:
        return False, "LFG post not found."
    creator_id, status, channel_id, message_id, guild_id = post
    if guild is None and guild_id:
        guild = client.get_guild(int(guild_id))
    if guild is None:
        return False, "Could not find the server for this LFG post."
    if user_id != int(creator_id):
        return False, "Only the creator can mark the group as filled."
    if status == "COMPLETED":
        return False, "This LFG post is already marked as filled."

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE lfg_posts SET status='COMPLETED' WHERE id=?", (lfg_id,))
        await db.commit()

    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if isinstance(channel, discord.TextChannel) and message_id:
        try:
            msg = await channel.fetch_message(int(message_id))
            if msg.embeds:
                embed = msg.embeds[0]
                embed.color = discord.Color.green()
                old_title = embed.title or "Looking for Group"
                if not old_title.startswith("[FILLED"):
                    embed.title = f"[FILLED ✅] {old_title}"
                embed.set_footer(text="✅ Group filled — post will auto-archive soon")
                await msg.edit(embed=embed)
        except (discord.NotFound, discord.HTTPException):
            pass

    return True, "Group marked as filled! Your LFG post now shows **[FILLED ✅]**."


class LFGDMMarkFilledView(discord.ui.View):
    """Persistent button sent in the group-full DM."""

    def __init__(self, lfg_id: int):
        super().__init__(timeout=None)
        self.lfg_id = lfg_id
        btn = discord.ui.Button(
            label="Mark as Filled",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"lfg:{lfg_id}:dm_fill",
        )
        btn.callback = self._mark_filled
        self.add_item(btn)

    async def _mark_filled(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, msg = await mark_lfg_filled(
            self.lfg_id,
            interaction.user.id,
            client=interaction.client,
            guild=interaction.guild,
        )
        if not ok:
            return await interaction.followup.send(msg, ephemeral=True)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass
        await interaction.followup.send(msg, ephemeral=True)
