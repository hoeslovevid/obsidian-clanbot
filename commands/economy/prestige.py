"""Prestige system - allow users to reset level for special rewards."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc, get_user_xp, add_xp, add_coins
import aiosqlite


async def get_user_prestige(guild_id: int, user_id: int) -> dict:
    """Get user's prestige information."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT prestige_level, total_prestige_xp, last_prestige_at
            FROM user_prestige
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        
        if row:
            return {
                "prestige_level": row[0] or 0,
                "total_prestige_xp": row[1] or 0,
                "last_prestige_at": row[2]
            }
        return {"prestige_level": 0, "total_prestige_xp": 0, "last_prestige_at": None}


async def prestige_user(guild_id: int, user_id: int, current_level: int, current_xp: int) -> dict:
    """Prestige a user - reset their level and award prestige rewards."""
    # Calculate prestige rewards
    prestige_xp_bonus = current_level * 100  # Bonus XP based on level
    prestige_coin_reward = current_level * 50  # Coin reward
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get current prestige level
        cur = await db.execute("""
            SELECT prestige_level FROM user_prestige
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        current_prestige = row[0] if row else 0
        new_prestige = current_prestige + 1
        
        # Update prestige
        await db.execute("""
            INSERT INTO user_prestige (guild_id, user_id, prestige_level, total_prestige_xp, last_prestige_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                prestige_level = prestige_level + 1,
                total_prestige_xp = total_prestige_xp + ?,
                last_prestige_at = ?
        """, (guild_id, user_id, new_prestige, prestige_xp_bonus, now_utc().isoformat(), prestige_xp_bonus, now_utc().isoformat()))
        
        # Reset XP to 0
        await db.execute("""
            UPDATE user_xp
            SET xp = 0, level = 0
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        
        # Award rewards
        await add_coins(guild_id, user_id, prestige_coin_reward, "PRESTIGE", f"Prestige {new_prestige} reward")
        await add_xp(guild_id, user_id, prestige_xp_bonus, "PRESTIGE_BONUS")
        
        await db.commit()
    
    return {
        "prestige_level": new_prestige,
        "coin_reward": prestige_coin_reward,
        "xp_bonus": prestige_xp_bonus
    }


def setup(bot, group=None):
    """Register prestige commands."""
    # Prestige command
    prestige_decorator = group.command(name="prestige", description="Reset your level for prestige rewards.") if group else bot.tree.command(name="prestige", description="Reset your level for prestige rewards.")
    
    @prestige_decorator
    async def prestige(interaction: discord.Interaction):
        """Prestige - reset level for special rewards."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Prestige can only be used in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        # Get current level and XP
        from database import get_user_xp
        xp, level, total_xp = await get_user_xp(interaction.guild.id, interaction.user.id)
        
        # Check minimum level requirement (e.g., level 50)
        min_level = 50
        if level < min_level:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Level Too Low",
                    f"You need to reach level {min_level} before you can prestige.\n\n"
                    f"**Your Level:** {level}\n"
                    f"**Required:** {min_level}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Get current prestige
        prestige_info = await get_user_prestige(interaction.guild.id, interaction.user.id)
        
        # Calculate rewards
        result = await prestige_user(interaction.guild.id, interaction.user.id, level, xp)
        
        # Send confirmation
        embed = obsidian_embed(
            "⭐ Prestige Complete!",
            f"Congratulations! You have reached **Prestige {result['prestige_level']}**!\n\n"
            f"**Rewards:**\n"
            f"• {result['coin_reward']:,} coins\n"
            f"• {result['xp_bonus']:,} bonus XP\n\n"
            f"Your level has been reset to 0, but you keep your total XP progress!\n"
            f"**Total Prestige XP:** {prestige_info['total_prestige_xp'] + result['xp_bonus']:,}",
            color=discord.Color.gold(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    # Prestige info command
    info_decorator = group.command(name="prestige_info", description="View your prestige information.") if group else bot.tree.command(name="prestige_info", description="View your prestige information.")
    
    @info_decorator
    @app_commands.describe(user="User to view prestige of (defaults to yourself)")
    async def prestige_info(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """View prestige information."""
        await interaction.response.defer(ephemeral=False)

        if not interaction.guild:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Context",
                    "Prestige info can only be viewed in a server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True,
            )

        target_user = user or interaction.user
        if not isinstance(target_user, discord.Member):
            return await interaction.followup.send("User not found in this server.", ephemeral=True)
        
        prestige_info = await get_user_prestige(interaction.guild.id, target_user.id)
        xp, level, total_xp = await get_user_xp(interaction.guild.id, target_user.id)
        
        embed = obsidian_embed(
            f"⭐ {target_user.display_name}'s Prestige",
            f"**Prestige Level:** {prestige_info['prestige_level']}\n"
            f"**Total Prestige XP:** {prestige_info['total_prestige_xp']:,}\n"
            f"**Current Level:** {level}\n"
            f"**Current XP:** {xp:,}\n"
            f"**Total XP:** {total_xp:,}\n\n"
            f"*Prestige to reset your level and gain special rewards!*",
            color=discord.Color.gold(),
            author=target_user,
            client=interaction.client,
        )
        
        if prestige_info['last_prestige_at']:
            embed.set_footer(text=f"Last prestiged: {prestige_info['last_prestige_at']}")
        
        await interaction.followup.send(embed=embed)
