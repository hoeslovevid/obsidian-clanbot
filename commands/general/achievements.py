"""Achievements system commands."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed
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
        bar_len = 10
        filled = int(bar_len * pct / 100)
        progress_bar = "█" * filled + "░" * (bar_len - filled)
        
        fields = [
            ("📊 Progress", f"**{unlocked_count}/{total_ach}** unlocked\n`[{progress_bar}]` {pct}%", True),
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
        embed = obsidian_embed(
            "🏆 Available Achievements",
            desc[:4000],
            color=discord.Color.blue(),
            thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
            footer=f"{total_ach} achievement(s) available • ✅ = unlocked, 🔒 = locked",
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
