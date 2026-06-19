"""Achievements system commands."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, render_bar
from core.leaderboard_privacy import leaderboard_display_name, user_hides_from_leaderboards
from database import DB_PATH, add_coins, add_xp
import aiosqlite  # type: ignore


def setup(bot, group=None):
    """Register achievement commands."""
    
    command_decorator = group.command(name="achievements", description="View your unlocked achievements.") if group else bot.tree.command(name="achievements", description="View your unlocked achievements.")
    
    @command_decorator
    async def achievements(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """View achievements."""
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
        
        target = user or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if not target:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Invalid User",
                    "Could not determine target user.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=(user is None))
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT a.achievement_id, a.unlocked_at, ad.name, ad.description, ad.category
                FROM achievements a
                JOIN achievement_definitions ad ON a.achievement_id = ad.achievement_id
                WHERE a.guild_id=? AND a.user_id=?
                ORDER BY a.unlocked_at DESC
            """, (interaction.guild.id, target.id))
            rows = await cur.fetchall()
            cur2 = await db.execute("SELECT COUNT(*) FROM achievement_definitions")
            total_ach = (await cur2.fetchone())[0] or 0
        
        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "🏆 No Achievements",
                    f"{target.mention} hasn't unlocked any achievements yet.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=(user is None)
            )
        
        achievements_by_category = {}
        for achievement_id, unlocked_at, name, description, category in rows:
            if category not in achievements_by_category:
                achievements_by_category[category] = []
            achievements_by_category[category].append((name, description, unlocked_at))
        
        unlocked_count = len(rows)
        pct = min(100, int(100 * unlocked_count / total_ach)) if total_ach > 0 else 0

        fields = [
            ("📊 Progress", f"**{unlocked_count}/{total_ach}** unlocked\n{render_bar(pct)}", True),
        ]
        for category, achievement_list in achievements_by_category.items():
            cat_text = "\n".join(f"🏆 **{name}**\n{desc}" for name, desc, _ in achievement_list[:5])
            if len(achievement_list) > 5:
                cat_text += f"\n_...and {len(achievement_list) - 5} more_"
            fields.append((category.replace("_", " ").title(), cat_text[:1024], False))
        
        embed = obsidian_embed(
            f"🏆 Achievements - {target.display_name}",
            f"Unlocked achievements for {target.mention}",
            color=discord.Color.gold(),
            thumbnail=target.display_avatar.url if target.display_avatar else None,
            fields=fields,
            footer=f"{unlocked_count} achievement(s) unlocked",
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=(user is None))
    
    lb_decorator = group.command(name="achievements_leaderboard", description="See who has unlocked the most achievements.") if group else bot.tree.command(name="achievements_leaderboard", description="Achievement count leaderboard.")

    @lb_decorator
    async def achievements_leaderboard(interaction: discord.Interaction):
        """Rank members by number of achievements unlocked."""
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Invalid Context", "This command can only be used in a server.", color=discord.Color.red(), client=interaction.client),
                ephemeral=True,
            )
        await interaction.response.defer()

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, COUNT(*) AS cnt
                FROM achievements
                WHERE guild_id=?
                GROUP BY user_id
                ORDER BY cnt DESC
                LIMIT 15
            """, (interaction.guild.id,))
            rows = await cur.fetchall()

            cur2 = await db.execute("SELECT COUNT(*) FROM achievement_definitions")
            total_ach = (await cur2.fetchone())[0] or 0

        if not rows:
            return await interaction.followup.send(
                embed=obsidian_embed("🏆 No Data", "No one has unlocked any achievements yet.", category="prestige", client=interaction.client),
            )

        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        viewer_rank = None
        for pos, (uid, cnt) in enumerate(rows, 1):
            name = await leaderboard_display_name(interaction.guild, uid)
            medal = medals.get(pos, f"**#{pos}**")
            bar = render_bar(int(100 * cnt / total_ach) if total_ach else 0, length=8, show_pct=False)
            lines.append(f"{medal} **{name}** — {cnt}/{total_ach} {bar}")
            if uid == interaction.user.id:
                viewer_rank = pos

        # Viewer's rank if not in top 15
        if viewer_rank is None:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT user_id, COUNT(*) AS cnt FROM achievements WHERE guild_id=? GROUP BY user_id
                    ) WHERE cnt >= (
                        SELECT COALESCE(COUNT(*), 0) FROM achievements WHERE guild_id=? AND user_id=?
                    )
                """, (interaction.guild.id, interaction.guild.id, interaction.user.id))
                rank_row = await cur.fetchone()
                viewer_rank = rank_row[0] if rank_row else None
            hidden = await user_hides_from_leaderboards(interaction.guild.id, interaction.user.id)
            rank_label = "Your rank (hidden)" if hidden else "Your rank"
            rank_suffix = f"\n-# {rank_label}: #{viewer_rank}" if viewer_rank else ""
        else:
            rank_suffix = f"\n-# Your rank: #{viewer_rank}"

        embed = obsidian_embed(
            "🏆 Achievement Leaderboard",
            "\n".join(lines) + rank_suffix,
            category="prestige",
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{total_ach} achievements available  ·  Top 15 shown",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed)

    command_decorator = group.command(name="achievement_list", description="View all available achievements.") if group else bot.tree.command(name="achievement_list", description="View all available achievements.")
    
    @command_decorator
    async def achievement_list(interaction: discord.Interaction):
        """List all achievements."""
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
        
        await interaction.response.defer(ephemeral=True)
        
        # Get all achievement definitions and which ones user has unlocked (same connection)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT achievement_id, name, description, category, requirement, reward_coins, reward_xp
                FROM achievement_definitions
                ORDER BY category, name
            """)
            rows = await cur.fetchall()
            
            if not rows:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "🏆 No Achievements Defined",
                        "No achievements are available yet.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check which ones user has unlocked
            cur = await db.execute("""
                SELECT achievement_id FROM achievements
                WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            unlocked_ids = {row[0] for row in await cur.fetchall()}
        
        # Group by category
        achievements_by_category = {}
        for achievement_id, name, description, category, requirement, reward_coins, reward_xp in rows:
            if category not in achievements_by_category:
                achievements_by_category[category] = []
            is_unlocked = achievement_id in unlocked_ids
            achievements_by_category[category].append((
                name, description, requirement, reward_coins, reward_xp, is_unlocked
            ))
        
        # Build description
        desc = ""
        for category, achievement_list in achievements_by_category.items():
            desc += f"**{category.replace('_', ' ').title()}:**\n"
            for name, description, requirement, reward_coins, reward_xp, is_unlocked in achievement_list:
                status = "✅" if is_unlocked else "🔒"
                desc += f"{status} **{name}**"
                if requirement:
                    desc += f" - *{requirement}*"
                if reward_coins or reward_xp:
                    rewards = []
                    if reward_coins:
                        rewards.append(f"{reward_coins} coins")
                    if reward_xp:
                        rewards.append(f"{reward_xp} XP")
                    desc += f" ({', '.join(rewards)})"
                desc += "\n"
            desc += "\n"
        
        total_ach = len(rows)
        from core.first_run_nudge import maybe_first_run_hint
        desc = await maybe_first_run_hint(
            interaction.guild.id, interaction.user.id, desc[:4000], feature="achievements"
        )
        embed = obsidian_embed(
            "🏆 Available Achievements",
            desc,
            color=discord.Color.blue(),
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{total_ach} achievement(s) available • ✅ = unlocked, 🔒 = locked",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
