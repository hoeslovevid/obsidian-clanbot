"""XP Leaderboard command."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, XP_ENABLED


def setup(bot, group=None):
    """Register the xpleaderboard command."""
    command_decorator = group.command(name="leaderboard", description="View the top XP earners.") if group else bot.tree.command(name="leaderboard", description="View the top XP earners.")
    
    @command_decorator
    @app_commands.describe(limit="Number of users to show (default: 10, max: 25)")
    async def xpleaderboard(interaction: discord.Interaction, limit: int = 10):
        """Display the top XP earners."""
        from bot import DB_PATH
        import aiosqlite
        
        if not XP_ENABLED:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ XP System Disabled",
                    "The XP system is currently disabled.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
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
        
        if limit < 1 or limit > 25:
            limit = 10
        
        await interaction.response.defer(ephemeral=False)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, xp, level, total_xp
                FROM user_xp
                WHERE guild_id=?
                ORDER BY xp DESC
                LIMIT ?
            """, (interaction.guild.id, limit))
            rows = await cur.fetchall()
            
            cur2 = await db.execute(
                "SELECT COUNT(*) FROM user_xp WHERE guild_id=? AND xp > 0",
                (interaction.guild.id,),
            )
            total_count = (await cur2.fetchone())[0]
            
            cur3 = await db.execute("""
                SELECT COUNT(*) + 1 FROM user_xp a
                WHERE a.guild_id=? AND a.xp > COALESCE(
                    (SELECT b.xp FROM user_xp b WHERE b.guild_id=? AND b.user_id=?), 0
                )
            """, (interaction.guild.id, interaction.guild.id, interaction.user.id))
            user_rank_row = await cur3.fetchone()
            user_rank = user_rank_row[0] if user_rank_row else None
            in_top = any(r[0] == interaction.user.id for r in rows)
            
            urow = None
            if not in_top and user_rank is not None:
                cur4 = await db.execute(
                    "SELECT xp, level, total_xp FROM user_xp WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, interaction.user.id),
                )
                urow = await cur4.fetchone()
        
        if not rows:
            if total_count == 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "⭐ Leaderboard Empty",
                        "No users have earned XP yet!\n\n_→ Start using commands and chatting to earn XP._",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "⭐ Leaderboard Empty",
                    "No users with XP yet.\n\n_→ Chat and use commands to earn XP and appear on the leaderboard._",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        leaderboard_text = ""
        for i, (user_id, xp, level, total_xp) in enumerate(rows, 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
            leaderboard_text += f"{medal} **{username}** — ⭐ Lv{level} • 💎 {xp:,} XP • 📊 {total_xp:,} total\n"
        
        you_line = ""
        if not in_top and user_rank is not None and urow and (urow[0] or 0) > 0:
            you_line = f"\n_You're here: **#{user_rank}** • {urow[0]:,} XP_"
        
        thumb_url = None
        if rows:
            top_user = interaction.guild.get_member(rows[0][0])
            if top_user and top_user.display_avatar:
                thumb_url = top_user.display_avatar.url
        
        embed = obsidian_embed(
            "⭐ XP Leaderboard",
            f"Top {len(rows)} XP earners{you_line}",
            color=discord.Color.blue(),
            thumbnail=thumb_url,
            fields=[("Rankings", leaderboard_text.strip(), False)],
            footer=f"{interaction.guild.name} • {total_count} users with XP",
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
