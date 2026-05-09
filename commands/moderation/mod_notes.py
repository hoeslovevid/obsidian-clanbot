"""Mod notes - private notes per user (mods only)."""
import discord
from discord import app_commands
from datetime import datetime

from core.utils import obsidian_embed, is_mod, copy_friendly_id, EMBED_COLORS
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register mod notes commands."""
    cmd = group.command(name="notes", description="View mod notes for a user (mods only).") if group else bot.tree.command(name="notes", description="View mod notes for a user.")
    add_cmd = group.command(name="note_add", description="Add a private mod note (mods only).") if group else bot.tree.command(name="note_add", description="Add a mod note.")

    @cmd
    @app_commands.describe(user="User to view notes for")
    async def notes(interaction: discord.Interaction, user: discord.Member):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, moderator_id, note, created_at FROM mod_notes
                WHERE guild_id=? AND target_user_id=? ORDER BY created_at DESC LIMIT 20
            """, (interaction.guild.id, user.id))
            rows = await cur.fetchall()
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed("Mod Notes", f"No notes for {user.mention}.", color=EMBED_COLORS["moderation"], client=interaction.client),
                ephemeral=True,
            )
        lines = []
        for nid, mod_id, note, created_at in rows:
            mod = interaction.guild.get_member(mod_id)
            mod_name = mod.display_name if mod else f"ID {mod_id}"
            try:
                dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                ts = int(dt.timestamp())
            except Exception:
                ts = 0
            lines.append(f"{copy_friendly_id(nid)} **{mod_name}** • <t:{ts}:R>\n{note[:200]}")
        desc = "\n\n".join(lines)
        embed = obsidian_embed(
            f"Mod Notes: {user.display_name}",
            desc,
            color=EMBED_COLORS["moderation"],
            footer="Mod only • Notes are private",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @add_cmd
    @app_commands.describe(user="User to add note for", note="Private note (not visible to user)")
    async def note_add(interaction: discord.Interaction, user: discord.Member, note: str):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Mods only.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Use this in a server.", ephemeral=True)
        if len(note) > 500:
            return await interaction.response.send_message("Note max 500 chars.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO mod_notes (guild_id, target_user_id, moderator_id, note, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (interaction.guild.id, user.id, interaction.user.id, note[:500], now_utc().isoformat()))
            await db.commit()
        await interaction.response.send_message(
            embed=obsidian_embed("Note Added", f"Note added for {user.mention}.", color=EMBED_COLORS["success"], client=interaction.client),
            ephemeral=True,
        )
