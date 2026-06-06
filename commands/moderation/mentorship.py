"""Mentorship pairing — mods assign mentor/mentee with optional thread."""
from __future__ import annotations

import discord
from discord import app_commands

from core.embed_templates import embed_template
from core.utils import error_embed, is_mod, success_embed
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register `/admin mentorship` subcommands."""

    @group.command(name="mentorship", description="Assign or list mentor/mentee pairs.")
    @app_commands.describe(
        action="assign, remove, or list pairs",
        mentor="Mentor member (assign only)",
        mentee="Mentee member (assign only)",
        create_thread="Open a private thread for the pair (assign only)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Assign", value="assign"),
        app_commands.Choice(name="Remove", value="remove"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def mentorship(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        mentor: discord.Member | None = None,
        mentee: discord.Member | None = None,
        create_thread: bool = True,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Moderators only.", client=interaction.client),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id

        if action.value == "list":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT mentor_id, mentee_id, thread_id, created_at FROM mentorship_pairs "
                    "WHERE guild_id=? AND status='active' ORDER BY created_at DESC LIMIT 15",
                    (gid,),
                )
                rows = await cur.fetchall()
            if not rows:
                return await interaction.followup.send(
                    embed=embed_template(
                        "showcase",
                        "🤝 Mentorship",
                        "No active mentor pairs.",
                        category="moderation",
                        client=interaction.client,
                    ),
                    ephemeral=True,
                )
            lines = []
            for mid, meid, tid, created in rows:
                m = interaction.guild.get_member(int(mid))
                me = interaction.guild.get_member(int(meid))
                thread_note = f" · <#{tid}>" if tid else ""
                lines.append(
                    f"• **{m.display_name if m else mid}** → **{me.display_name if me else meid}**{thread_note}"
                )
            return await interaction.followup.send(
                embed=embed_template(
                    "showcase",
                    "🤝 Active Mentorship Pairs",
                    "\n".join(lines),
                    category="moderation",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if action.value == "remove":
            if not mentee:
                return await interaction.followup.send("Provide **mentee** to remove.", ephemeral=True)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE mentorship_pairs SET status='removed' WHERE guild_id=? AND mentee_id=?",
                    (gid, mentee.id),
                )
                await db.commit()
            return await interaction.followup.send(
                embed=success_embed(
                    "Pair Removed",
                    f"Mentorship for {mentee.mention} has been ended.",
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        if not mentor or not mentee:
            return await interaction.followup.send("**mentor** and **mentee** are required for assign.", ephemeral=True)
        if mentor.id == mentee.id:
            return await interaction.followup.send("Mentor and mentee must be different members.", ephemeral=True)

        thread_id = None
        if create_thread and isinstance(interaction.channel, discord.TextChannel):
            try:
                thread = await interaction.channel.create_thread(
                    name=f"Mentor-{mentor.display_name[:20]}-{mentee.display_name[:20]}",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    reason="Mentorship pairing",
                )
                await thread.add_user(mentor)
                await thread.add_user(mentee)
                thread_id = thread.id
                await thread.send(
                    f"🤝 Mentorship thread — **{mentor.mention}** mentoring **{mentee.mention}**.\n"
                    f"Assigned by {interaction.user.mention}.",
                )
            except discord.HTTPException:
                thread_id = None

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO mentorship_pairs "
                "(guild_id, mentor_id, mentee_id, thread_id, status, created_by, created_at) "
                "VALUES (?,?,?,?, 'active', ?, ?)",
                (gid, mentor.id, mentee.id, thread_id, interaction.user.id, now_utc().isoformat()),
            )
            await db.commit()

        msg = f"**{mentor.display_name}** is now mentoring **{mentee.display_name}**."
        if thread_id:
            msg += f"\nThread: <#{thread_id}>"
        await interaction.followup.send(
            embed=success_embed("Mentorship Assigned", msg, client=interaction.client),
            ephemeral=True,
        )
