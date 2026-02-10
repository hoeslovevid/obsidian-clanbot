"""Leaderboard command."""
import discord
from discord import app_commands

from utils import obsidian_embed, ECONOMY_ENABLED


def setup(bot, group=None):
    """Register the leaderboard command."""
    command_decorator = group.command(name="leaderboard", description="View the top coin earners.") if group else bot.tree.command(name="leaderboard", description="View the top coin earners.")
    
    @command_decorator
    @app_commands.describe(
        limit="Number of users to show (default: 10, max: 25)",
        sort_by="Sort order: by current balance or total earned"
    )
    @app_commands.choices(sort_by=[
        app_commands.Choice(name="Balance (current)", value="balance"),
        app_commands.Choice(name="Total Earned", value="total_earned"),
    ])
    async def leaderboard(interaction: discord.Interaction, limit: int = 10, sort_by: app_commands.Choice[str] = None):
        """Display the top coin earners."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import DB_PATH
        import aiosqlite
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Economy Disabled",
                    "The economy system is currently disabled.",
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
        order_col = "total_earned" if sort_by and sort_by.value == "total_earned" else "balance"
        await interaction.response.defer(ephemeral=False)
        sort_label = "total earned" if order_col == "total_earned" else "balance"

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                f"""
                SELECT user_id, balance, total_earned
                FROM user_balances
                WHERE guild_id=? AND (balance > 0 OR total_earned > 0)
                ORDER BY {order_col} DESC
                LIMIT ?
                """,
                (interaction.guild.id, limit),
            )
            rows = await cur.fetchall()

            # Get total count (users with economy activity) in same connection
            cur2 = await db.execute(
                "SELECT COUNT(*) FROM user_balances WHERE guild_id=? AND (balance > 0 OR total_earned > 0)",
                (interaction.guild.id,),
            )
            total_count = (await cur2.fetchone())[0]

            cur3 = await db.execute(
                f"""
                SELECT COUNT(*) + 1 FROM user_balances a
                WHERE a.guild_id=? AND a.{order_col} > COALESCE(
                    (SELECT b.{order_col} FROM user_balances b WHERE b.guild_id=? AND b.user_id=?), 0
                )
                """,
                (interaction.guild.id, interaction.guild.id, interaction.user.id),
            )
            user_rank_row = await cur3.fetchone()
            user_rank = user_rank_row[0] if user_rank_row else None
            in_top = any(r[0] == interaction.user.id for r in rows)

            # Get viewer's balance/total for "You're here" in same connection
            urow = None
            if not in_top and user_rank is not None:
                cur4 = await db.execute(
                    "SELECT balance, total_earned FROM user_balances WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, interaction.user.id),
                )
                urow = await cur4.fetchone()
        
        if not rows:
            
            if total_count == 0:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📊 Leaderboard Empty",
                        "No users have earned coins yet! Start chatting or use `/daily` to earn coins.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            else:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📊 Leaderboard Empty",
                        "No users currently have coins! Users need a balance greater than 0 to appear on the leaderboard.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        # Build leaderboard entries with inline fields for top 3
        leaderboard_text = ""
        for i, (user_id, balance, total_earned) in enumerate(rows, 1):
            user = interaction.guild.get_member(user_id)
            username = user.display_name if user else f"User {user_id}"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
            leaderboard_text += f"{medal} **{username}** — 💰 {balance:,} • 📊 {total_earned:,}\n"

        # "You're here" when not in top N (urow already fetched above)
        you_line = ""
        if not in_top and user_rank is not None and urow and (urow[0] or 0) + (urow[1] or 0) > 0:
            val = urow[1] if order_col == "total_earned" else urow[0]
            lbl = "total earned" if order_col == "total_earned" else "coins"
            you_line = f"\n_You're here: **#{user_rank}** • {val:,} {lbl}_"

        # Use first-place user's avatar as thumbnail if available
        thumb_url = None
        if rows:
            top_user = interaction.guild.get_member(rows[0][0])
            if top_user and top_user.display_avatar:
                thumb_url = top_user.display_avatar.url

        embed = obsidian_embed(
            "🏆 Coin Leaderboard",
            f"Top {len(rows)} by {sort_label}{you_line}",
            color=discord.Color.gold(),
            thumbnail=thumb_url,
            fields=[("Rankings", leaderboard_text.strip(), False)],
            footer=f"{interaction.guild.name} • {total_count} users with economy activity",
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=False)
