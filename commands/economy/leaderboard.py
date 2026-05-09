"""Leaderboard command."""
import discord
from discord import app_commands

from core.utils import obsidian_embed, feature_off_embed, ECONOMY_ENABLED
from views import EmbedPaginator


def setup(bot, group=None):
    """Register the leaderboard command under economy and as top-level /leaderboard shortcut."""
    @app_commands.describe(
        limit="Number of users per page (default: 15, max: 25)",
        sort_by="Sort order: by current balance or total earned"
    )
    @app_commands.choices(sort_by=[
        app_commands.Choice(name="Balance (current)", value="balance"),
        app_commands.Choice(name="Total Earned", value="total_earned"),
    ])
    async def leaderboard_callback(interaction: discord.Interaction, limit: int = 15, sort_by: app_commands.Choice[str] = None):
        """Display the top coin earners."""
        # Import bot-specific functions inside to avoid circular imports
        from bot import DB_PATH
        import aiosqlite
        
        if not ECONOMY_ENABLED:
            return await interaction.response.send_message(
                embed=feature_off_embed("Economy", "Ask a moderator to enable it in the bot config.", client=interaction.client),
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
            limit = 15
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
                (interaction.guild.id, 50),
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
                        "No users have earned coins yet!\n\n_→ Start chatting or use `/daily` to earn coins._",
                        color=discord.Color.orange(),
                        footer="Use /balance to check your coins • /help for all commands",
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            else:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📊 Leaderboard Empty",
                        "No users currently have coins.\n\n_→ Chat or use `/daily` to earn coins and appear on the leaderboard._",
                        color=discord.Color.orange(),
                        footer="Use /balance to check your coins • /help for all commands",
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        per_page = min(limit, 15)
        pages = []
        for p in range(0, len(rows), per_page):
            page_rows = rows[p:p + per_page]
            leaderboard_text = ""
            for i, (user_id, balance, total_earned) in enumerate(page_rows, p + 1):
                user = interaction.guild.get_member(user_id)
                username = user.display_name if user else f"User {user_id}"
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
                leaderboard_text += f"{medal} **{username}** — 💰 {balance:,} • 📊 {total_earned:,}\n"

            you_line = ""
            if not in_top and user_rank is not None and urow and (urow[0] or 0) + (urow[1] or 0) > 0 and p == 0:
                val = urow[1] if order_col == "total_earned" else urow[0]
                lbl = "total earned" if order_col == "total_earned" else "coins"
                you_line = f"\n_You're here: **#{user_rank}** • {val:,} {lbl}_"

            thumb_url = None
            if page_rows:
                top_user = interaction.guild.get_member(page_rows[0][0])
                if top_user and top_user.display_avatar:
                    thumb_url = top_user.display_avatar.url

            pages.append({
                "description": f"Top {len(rows)} by {sort_label}{you_line}",
                "fields": [("Rankings", leaderboard_text.strip(), False)],
                "footer": f"{interaction.guild.name} • Page {len(pages) + 1}/{(len(rows) + per_page - 1) // per_page} • {total_count} users",
                "thumbnail": thumb_url,
            })

        if len(pages) == 1:
            p0 = pages[0]
            embed = obsidian_embed(
                "🏆 Coin Leaderboard",
                p0["description"],
                color=discord.Color.gold(),
                thumbnail=p0.get("thumbnail"),
                fields=p0.get("fields"),
                footer=p0.get("footer"),
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=False)
        else:
            paginator_pages = []
            for p in pages:
                paginator_pages.append({
                    "description": p["description"],
                    "fields": p["fields"],
                    "footer": p["footer"],
                    "thumbnail": p.get("thumbnail"),
                })
            paginator = EmbedPaginator("🏆 Coin Leaderboard", paginator_pages, color=discord.Color.gold(), client=interaction.client, total_items=total_count, per_page=per_page)
            first_embed = obsidian_embed(
                "🏆 Coin Leaderboard",
                paginator_pages[0]["description"],
                color=discord.Color.gold(),
                thumbnail=pages[0].get("thumbnail"),
                fields=paginator_pages[0]["fields"],
                footer=paginator_pages[0]["footer"],
                client=interaction.client,
            )
            await interaction.followup.send(embed=first_embed, view=paginator, ephemeral=False)

    group.command(name="leaderboard", description="View the top coin earners.")(leaderboard_callback)
    shortcut = app_commands.Command(name="leaderboard", description="View top coin earners (shortcut for /economy leaderboard)", callback=leaderboard_callback)
    bot.tree.add_command(shortcut)
