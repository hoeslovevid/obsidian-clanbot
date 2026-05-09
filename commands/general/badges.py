"""Badge and title system for user customization."""
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, feature_off_embed, is_mod
from database import (
    DB_PATH, now_utc,
    get_all_title_definitions,
    get_user_unlocked_titles,
    unlock_title_for_user,
    check_and_unlock_eligible_titles,
    get_user_balance,
    remove_coins,
)
from core.config import ECONOMY_ENABLED
import aiosqlite


async def get_user_badges(guild_id: int, user_id: int) -> list:
    """Get user's badges."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT ub.badge_id, ub.unlocked_at, ub.is_equipped, bd.name, bd.description, bd.icon_emoji, bd.rarity
            FROM user_badges ub
            LEFT JOIN badge_definitions bd ON ub.badge_id = bd.badge_id
            WHERE ub.guild_id=? AND ub.user_id=?
            ORDER BY ub.is_equipped DESC, ub.unlocked_at DESC
        """, (guild_id, user_id))
        return await cur.fetchall()


async def get_user_title(guild_id: int, user_id: int) -> Optional[str]:
    """Get user's custom title."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT title FROM user_titles
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        return row[0] if row else None


async def set_user_title(guild_id: int, user_id: int, title: Optional[str]):
    """Set user's custom title."""
    async with aiosqlite.connect(DB_PATH) as db:
        if title:
            await db.execute("""
                INSERT INTO user_titles (guild_id, user_id, title)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET title = excluded.title
            """, (guild_id, user_id, title))
        else:
            await db.execute("""
                DELETE FROM user_titles WHERE guild_id=? AND user_id=?
            """, (guild_id, user_id))
        await db.commit()


async def equip_badge(guild_id: int, user_id: int, badge_id: str):
    """Equip a badge (unequip others)."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Unequip all badges
        await db.execute("""
            UPDATE user_badges SET is_equipped = 0
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        
        # Equip the selected badge
        await db.execute("""
            UPDATE user_badges SET is_equipped = 1
            WHERE guild_id=? AND user_id=? AND badge_id=?
        """, (guild_id, user_id, badge_id))
        
        await db.commit()


def setup(bot, group=None):
    """Register badge and title commands."""
    # Badges command
    badges_decorator = group.command(name="badges", description="View your badges.") if group else bot.tree.command(name="badges", description="View your badges.")
    
    @badges_decorator
    @app_commands.describe(user="User to view badges of (defaults to yourself)")
    async def badges(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        """View user badges."""
        await interaction.response.defer(ephemeral=False)
        
        target_user = user or interaction.user
        if not isinstance(target_user, discord.Member):
            return await interaction.followup.send("User not found in this server.", ephemeral=True)
        
        badges_list = await get_user_badges(interaction.guild.id, target_user.id)
        
        if not badges_list:
            embed = obsidian_embed(
                f"🏆 {target_user.display_name}'s Badges",
                "No badges unlocked yet.\n\n*Earn badges by completing achievements and milestones!*",
                color=discord.Color.blurple(),
                author=target_user,
                client=interaction.client,
            )
            return await interaction.followup.send(embed=embed)
        
        # Group badges by equipped status
        equipped = [b for b in badges_list if b[2] == 1]
        unequipped = [b for b in badges_list if b[2] == 0]
        
        fields = []
        if equipped:
            equipped_text = ""
            for badge_id, unlocked_at, is_equipped, name, desc, emoji, rarity in equipped[:10]:
                badge_name = name or badge_id.replace("_", " ").title()
                emoji_str = emoji or "🏆"
                equipped_text += f"{emoji_str} **{badge_name}** ({rarity})\n"
            fields.append(("⭐ Equipped", equipped_text, False))
        
        if unequipped:
            unequipped_text = ""
            for badge_id, unlocked_at, is_equipped, name, desc, emoji, rarity in unequipped[:15]:
                badge_name = name or badge_id.replace("_", " ").title()
                emoji_str = emoji or "🏆"
                unequipped_text += f"{emoji_str} {badge_name}\n"
            if len(unequipped) > 15:
                unequipped_text += f"\n... and {len(unequipped) - 15} more"
            fields.append(("📦 Unlocked", unequipped_text, False))
        
        embed = obsidian_embed(
            f"🏆 {target_user.display_name}'s Badges",
            f"**Total Badges:** {len(badges_list)}\n**Equipped:** {len(equipped)}",
            color=discord.Color.gold(),
            author=target_user,
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
    
    # Title command
    title_decorator = group.command(name="title", description="Set or view your custom title.") if group else bot.tree.command(name="title", description="Set or view your custom title.")
    
    @title_decorator
    @app_commands.describe(
        action="Action to perform",
        title="Your custom title (max 32 characters, leave empty to remove)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set Title", value="set"),
        app_commands.Choice(name="View Title", value="view"),
        app_commands.Choice(name="Remove Title", value="remove"),
    ])
    async def title(interaction: discord.Interaction, action: str, title: Optional[str] = None, user: Optional[discord.Member] = None):
        """Manage custom titles."""
        await interaction.response.defer(ephemeral=True)
        
        target_user = user or interaction.user
        is_moderator = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # Users can only manage their own title unless they're a mod
        if target_user.id != interaction.user.id and not is_moderator:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "You can only manage your own title.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        if action == "set":
            if not title:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Title",
                        "Please provide a title to set.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if len(title) > 32:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Title Too Long",
                        "Titles must be 32 characters or less.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await set_user_title(interaction.guild.id, target_user.id, title)
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Title Set",
                    f"Your title has been set to: **{title}**",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action == "remove":
            await set_user_title(interaction.guild.id, target_user.id, None)
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Title Removed",
                    "Your title has been removed.",
                    color=discord.Color.orange(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action == "view":
            current_title = await get_user_title(interaction.guild.id, target_user.id)
            if current_title:
                embed = obsidian_embed(
                    f"👑 {target_user.display_name}'s Title",
                    f"**Title:** {current_title}",
                    color=discord.Color.gold(),
                    author=target_user,
                    client=interaction.client,
                )
            else:
                embed = obsidian_embed(
                    f"👑 {target_user.display_name}'s Title",
                    "No title set.\n\n*Use `/title set` to set a custom title!*",
                    color=discord.Color.blurple(),
                    author=target_user,
                    client=interaction.client,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    # Equip badge command
    equip_decorator = group.command(name="equip_badge", description="Equip a badge.") if group else bot.tree.command(name="equip_badge", description="Equip a badge.")
    
    @equip_decorator
    @app_commands.describe(badge_id="The badge ID to equip")
    async def equip_badge_cmd(interaction: discord.Interaction, badge_id: str):
        """Equip a badge."""
        await interaction.response.defer(ephemeral=True)
        
        # Check if user has the badge
        badges_list = await get_user_badges(interaction.guild.id, interaction.user.id)
        user_badge_ids = [b[0] for b in badges_list]
        
        if badge_id not in user_badge_ids:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Badge Not Found",
                    "You don't have this badge unlocked.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await equip_badge(interaction.guild.id, interaction.user.id, badge_id)
        
        # Get badge name
        badge_name = "Unknown"
        for b in badges_list:
            if b[0] == badge_id:
                badge_name = b[3] or badge_id.replace("_", " ").title()
                break
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Badge Equipped",
                f"You have equipped: **{badge_name}**",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )

    # Badge showcase (feature up to 5 badges on profile)
    showcase_decorator = group.command(name="badge_showcase", description="Set or view badge showcase (featured on profile).") if group else bot.tree.command(name="badge_showcase", description="Set or view badge showcase (featured on profile).")
    @showcase_decorator
    @app_commands.describe(
        action="Set, clear, or view showcase",
        slot="Slot 1-5 (for set/clear)",
        badge_id="Badge to feature (for set)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Set", value="set"),
        app_commands.Choice(name="Clear", value="clear"),
        app_commands.Choice(name="View", value="view"),
    ])
    async def showcase(
        interaction: discord.Interaction,
        action: str,
        slot: Optional[int] = None,
        badge_id: Optional[str] = None,
    ):
        """Manage badge showcase slots (1-5) displayed on profile."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            if action == "view":
                cur = await db.execute("""
                    SELECT ubs.slot, ubs.badge_id, bd.name, bd.icon_emoji
                    FROM user_badge_showcase ubs
                    LEFT JOIN badge_definitions bd ON ubs.badge_id = bd.badge_id
                    WHERE ubs.guild_id=? AND ubs.user_id=?
                    ORDER BY ubs.slot
                """, (interaction.guild.id, interaction.user.id))
                rows = await cur.fetchall()
                if not rows:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "⭐ Badge Showcase",
                            "No badges in showcase. Use `/tools badge_showcase` action:Set to add up to 5 badges.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                lines = [f"**Slot {s}:** {e or '🏆'} **{n or bid}**" for s, bid, n, e in rows]
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "⭐ Badge Showcase",
                        "\n".join(lines),
                        color=discord.Color.gold(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )

            if slot is None or slot < 1 or slot > 5:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Invalid Slot", "Slot must be 1-5.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )

            if action == "clear":
                await db.execute(
                    "DELETE FROM user_badge_showcase WHERE guild_id=? AND user_id=? AND slot=?",
                    (interaction.guild.id, interaction.user.id, slot),
                )
                await db.commit()
                return await interaction.followup.send(
                    embed=obsidian_embed("✅ Cleared", f"Slot {slot} cleared.", color=discord.Color.green(), client=interaction.client),
                    ephemeral=True
                )

            if action == "set":
                if not badge_id:
                    return await interaction.followup.send(
                        embed=obsidian_embed("❌ Missing Badge", "Provide badge_id to set.", color=discord.Color.red(), client=interaction.client),
                        ephemeral=True
                    )
                badges_list = await get_user_badges(interaction.guild.id, interaction.user.id)
                user_badge_ids = [b[0] for b in badges_list]
                if badge_id not in user_badge_ids:
                    return await interaction.followup.send(
                        embed=obsidian_embed("❌ Badge Not Found", "You don't have this badge.", color=discord.Color.red(), client=interaction.client),
                        ephemeral=True
                    )
                await db.execute("""
                    INSERT INTO user_badge_showcase (guild_id, user_id, slot, badge_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id, slot) DO UPDATE SET badge_id=excluded.badge_id
                """, (interaction.guild.id, interaction.user.id, slot, badge_id))
                await db.commit()
                badge_name = next((b[3] or b[0] for b in badges_list if b[0] == badge_id), badge_id)
                return await interaction.followup.send(
                    embed=obsidian_embed("✅ Showcase Set", f"Slot {slot}: **{badge_name}**", color=discord.Color.green(), client=interaction.client),
                    ephemeral=True
                )

    # Title shop: browse, unlock (purchase), equip preset titles
    title_shop_decorator = group.command(name="title_shop", description="Browse and equip unlockable titles.") if group else bot.tree.command(name="title_shop", description="Browse and equip unlockable titles.")
    @title_shop_decorator
    @app_commands.describe(action="Action to perform", title_id="Title ID (from browse)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Browse", value="browse"),
        app_commands.Choice(name="Equip", value="equip"),
        app_commands.Choice(name="Unlock (purchase)", value="unlock"),
    ])
    async def title_shop(interaction: discord.Interaction, action: str, title_id: Optional[str] = None):
        """Browse, unlock, and equip preset titles."""
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        # Check and unlock any newly eligible titles (balance, months, messages)
        await check_and_unlock_eligible_titles(interaction.guild.id, interaction.user.id)

        definitions = await get_all_title_definitions()
        unlocked = await get_user_unlocked_titles(interaction.guild.id, interaction.user.id)
        current_title = await get_user_title(interaction.guild.id, interaction.user.id)

        if action == "browse":
            lines = []
            for tid, name, desc, u_type, u_val, cost in definitions:
                status = "✅" if tid in unlocked else "🔒"
                req = ""
                if u_type == "purchase" and cost > 0:
                    req = f" — {cost:,} coins"
                elif u_type == "balance" and u_val:
                    req = f" — Reach {int(u_val):,} coins"
                elif u_type == "months" and u_val:
                    req = f" — {u_val} months in server"
                elif u_type == "messages" and u_val:
                    req = f" — {int(u_val):,} messages"
                lines.append(f"{status} **{name}** ({tid}){req}\n   _{desc}_")
            embed = obsidian_embed(
                "👑 Title Shop",
                "Unlock titles by meeting requirements or purchasing. Use `/tools title_shop` action:Equip to wear one.\n\n" + "\n\n".join(lines[:15]),
                color=discord.Color.gold(),
                author=interaction.user,
                client=interaction.client,
            )
            if current_title:
                embed.add_field(name="Current Title", value=current_title, inline=False)
            return await interaction.followup.send(embed=embed, ephemeral=True)

        if action == "equip":
            if not title_id:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Missing Title", "Provide title_id from browse (e.g. millionaire).", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            title_id = title_id.lower().strip()
            if title_id not in unlocked:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Locked", f"You haven't unlocked **{title_id}**. Meet the requirement or purchase it first.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            title_name = next((d[1] for d in definitions if d[0] == title_id), title_id)
            await set_user_title(interaction.guild.id, interaction.user.id, title_name)
            return await interaction.followup.send(
                embed=obsidian_embed("✅ Title Equipped", f"You are now: **{title_name}**", color=discord.Color.green(), client=interaction.client),
                ephemeral=True
            )

        if action == "unlock":
            if not title_id:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Missing Title", "Provide title_id to purchase.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            if not ECONOMY_ENABLED:
                return await interaction.followup.send(
                    embed=feature_off_embed("Economy", "Ask a moderator to enable economy to purchase titles.", client=interaction.client),
                    ephemeral=True
                )
            title_id = title_id.lower().strip()
            defn = next((d for d in definitions if d[0] == title_id), None)
            if not defn:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Unknown Title", f"No title **{title_id}** found.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            tid, name, desc, u_type, cost = defn[0], defn[1], defn[2], defn[3], defn[5]
            if u_type != "purchase" or cost <= 0:
                return await interaction.followup.send(
                    embed=obsidian_embed("ℹ️ Not Purchasable", f"**{name}** is unlocked by meeting requirements, not by purchase.", color=discord.Color.blue(), client=interaction.client),
                    ephemeral=True
                )
            if tid in unlocked:
                return await interaction.followup.send(
                    embed=obsidian_embed("✅ Already Owned", f"You already have **{name}**. Use equip to wear it.", color=discord.Color.green(), client=interaction.client),
                    ephemeral=True
                )
            balance = await get_user_balance(interaction.guild.id, interaction.user.id)
            if balance < cost:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Insufficient Coins", f"**{name}** costs {cost:,} coins. You have {balance:,}.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            ok = await remove_coins(interaction.guild.id, interaction.user.id, cost, "TITLE_PURCHASE", f"Purchased title: {name}")
            if not ok:
                return await interaction.followup.send(
                    embed=obsidian_embed("❌ Error", "Could not deduct coins.", color=discord.Color.red(), client=interaction.client),
                    ephemeral=True
                )
            await unlock_title_for_user(interaction.guild.id, interaction.user.id, tid)
            await set_user_title(interaction.guild.id, interaction.user.id, name)
            return await interaction.followup.send(
                embed=obsidian_embed("✅ Title Purchased", f"You bought and equipped **{name}** for {cost:,} coins!", color=discord.Color.green(), client=interaction.client),
                ephemeral=True
            )
