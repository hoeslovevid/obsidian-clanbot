"""Reputation system commands - rep/reputation moved to context menu."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed
from database import DB_PATH, now_utc
import aiosqlite


async def execute_give_rep(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
    """Give reputation to a user (called from slash or context menu)."""
    if not interaction.guild:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    if user.bot:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid User", "You cannot give reputation to bots.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    if user.id == interaction.user.id:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid User", "You cannot give reputation to yourself.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )

    await interaction.response.defer()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT 1 FROM reputation_history
            WHERE guild_id=? AND user_id=? AND giver_id=?
            AND datetime(created_at) > datetime('now', '-1 day')
        """, (interaction.guild.id, user.id, interaction.user.id))
        if await cur.fetchone():
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⏳ Cooldown",
                    f"You have already given reputation to {user.mention} in the last 24 hours.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
            )

        await db.execute("""
            INSERT OR REPLACE INTO reputation (guild_id, user_id, reputation_points)
            VALUES (?, ?, COALESCE((SELECT reputation_points FROM reputation WHERE guild_id=? AND user_id=?), 0) + 1)
        """, (interaction.guild.id, user.id, interaction.guild.id, user.id))
        await db.execute("""
            INSERT INTO reputation_history (guild_id, user_id, giver_id, points, reason, created_at)
            VALUES (?, ?, ?, 1, ?, ?)
        """, (interaction.guild.id, user.id, interaction.user.id, reason, now_utc().isoformat()))
        await db.commit()
        cur = await db.execute("SELECT reputation_points FROM reputation WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id))
        row = await cur.fetchone()
        rep_points = row[0] if row else 1

    await interaction.followup.send(
        embed=obsidian_embed(
            "✅ Reputation Given",
            f"**User:** {user.mention}\n**Reason:** {reason or 'No reason provided'}\n**New Reputation:** {rep_points}",
            color=discord.Color.green(),
            client=interaction.client,
        ),
    )


async def execute_view_rep(interaction: discord.Interaction, user: discord.Member):
    """View a user's reputation (called from context menu)."""
    if not interaction.guild:
        return await interaction.response.send_message(
            embed=obsidian_embed("❌ Invalid Context", "This can only be used in a server.", color=discord.Color.red(), client=interaction.client),
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT reputation_points FROM reputation WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id))
        row = await cur.fetchone()
        rep_points = row[0] if row else 0
        cur = await db.execute("""
            SELECT giver_id, points, reason, created_at FROM reputation_history
            WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 5
        """, (interaction.guild.id, user.id))
        history = await cur.fetchall()
    history_text = ""
    if history:
        lines = []
        for giver_id, points, reason, created_at in history:
            giver = interaction.guild.get_member(giver_id)
            giver_name = giver.display_name if giver else f"User {giver_id}"
            lines.append(f"**+{points}** from {giver_name}" + (f" - {reason}" if reason else ""))
        history_text = "\n".join(lines)
    else:
        history_text = "No reputation history."
    embed = obsidian_embed(
        f"⭐ Reputation: {user.display_name}",
        f"**Total Reputation:** {rep_points}\n\n**Recent History:**\n{history_text}",
        color=discord.Color.gold(),
        client=interaction.client,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


def setup(bot, group=None):
    """Register reputation commands (rep moved to context menu, keep reputation and reputation_leaderboard as slash)."""
    command_decorator = group.command(name="reputation", description="View a user's reputation.") if group else bot.tree.command(name="reputation", description="View a user's reputation.")

    @command_decorator
    @app_commands.describe(user="User to check reputation for")
    async def reputation(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """View user reputation."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        if not user:
            user = interaction.user if isinstance(interaction.user, discord.Member) else None
        if not user:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid User", "Please specify a user.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await execute_view_rep(interaction, user)

    command_decorator = group.command(name="reputation_leaderboard", description="View reputation leaderboard.") if group else bot.tree.command(name="reputation_leaderboard", description="View reputation leaderboard.")
    
    @command_decorator
    async def reputation_leaderboard(interaction: discord.Interaction):
        """View reputation leaderboard."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "This command can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer()
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, reputation_points FROM reputation
                WHERE guild_id=? ORDER BY reputation_points DESC LIMIT 10
            """, (interaction.guild.id,))
            leaderboard = await cur.fetchall()
        
        if not leaderboard:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⭐ Reputation Leaderboard",
                    "No reputation data yet.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
            )
        
        leaderboard_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, points) in enumerate(leaderboard):
            user = interaction.guild.get_member(user_id)
            user_name = user.display_name if user else f"User {user_id}"
            medal = medals[i] if i < 3 else f"{i+1}."
            leaderboard_text += f"{medal} **{user_name}** - {points} reputation\n"
        
        embed = obsidian_embed(
            "⭐ Reputation Leaderboard",
            leaderboard_text,
            color=discord.Color.gold(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)
