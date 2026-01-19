"""Server rules commands."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot):
    """Register rules commands."""
    
    @bot.tree.command(name="rules", description="View server rules.")
    async def rules(interaction: discord.Interaction):
        """Display server rules."""
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
        
        # Get rules
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT rule_number, rule_text FROM server_rules
                WHERE guild_id=? ORDER BY rule_number
            """, (interaction.guild.id,))
            rules_list = await cur.fetchall()
            
            # Check if user has accepted
            cur = await db.execute("""
                SELECT 1 FROM rule_acceptances WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            has_accepted = await cur.fetchone() is not None
        
        if not rules_list:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "📜 Server Rules",
                    "No rules have been set for this server yet.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build rules text
        rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
        
        if not has_accepted:
            rules_text += "\n\n⚠️ **You have not accepted these rules yet. Use `/accept_rules` to accept them.**"
        
        embed = obsidian_embed(
            "📜 Server Rules",
            rules_text,
            color=discord.Color.blue(),
            client=interaction.client,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @bot.tree.command(name="accept_rules", description="Accept the server rules.")
    async def accept_rules(interaction: discord.Interaction):
        """Accept server rules."""
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
        
        # Check if rules exist
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT 1 FROM server_rules WHERE guild_id=?", (interaction.guild.id,))
            if not await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ No Rules",
                        "No rules have been set for this server yet.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Check if already accepted
            cur = await db.execute("""
                SELECT 1 FROM rule_acceptances WHERE guild_id=? AND user_id=?
            """, (interaction.guild.id, interaction.user.id))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Accepted",
                        "You have already accepted the server rules.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Record acceptance
            await db.execute("""
                INSERT OR REPLACE INTO rule_acceptances (guild_id, user_id, accepted_at)
                VALUES (?, ?, ?)
            """, (interaction.guild.id, interaction.user.id, now_utc().isoformat()))
            await db.commit()
        
        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Rules Accepted",
                "You have accepted the server rules. Thank you!",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
    
    @bot.tree.command(name="rules_setup", description="Set up server rules (moderators only).")
    @app_commands.describe(action="Action to perform", rule_number="Rule number (for add/edit/remove)", rule_text="Rule text (for add/edit)")
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="edit", value="edit"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ])
    async def rules_setup(interaction: discord.Interaction, action: str, rule_number: Optional[int] = None, rule_text: Optional[str] = None):
        """Manage server rules."""
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
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed(
                    "❌ Permission Denied",
                    "Sorry, but you are not an Administrator in this server.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            if action == "add":
                if not rule_text:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Rule Text",
                            "Please provide the rule text.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                # Get next rule number
                cur = await db.execute("""
                    SELECT MAX(rule_number) FROM server_rules WHERE guild_id=?
                """, (interaction.guild.id,))
                row = await cur.fetchone()
                next_number = (row[0] or 0) + 1
                
                await db.execute("""
                    INSERT INTO server_rules (guild_id, rule_number, rule_text, created_at)
                    VALUES (?, ?, ?, ?)
                """, (interaction.guild.id, next_number, rule_text, now_utc().isoformat()))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Added",
                        f"Rule #{next_number} has been added.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "edit":
                if not rule_number or not rule_text:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Parameters",
                            "Please provide both rule number and rule text.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    UPDATE server_rules SET rule_text=? WHERE guild_id=? AND rule_number=?
                """, (rule_text, interaction.guild.id, rule_number))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Updated",
                        f"Rule #{rule_number} has been updated.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "remove":
                if not rule_number:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Rule Number",
                            "Please provide the rule number to remove.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    DELETE FROM server_rules WHERE guild_id=? AND rule_number=?
                """, (interaction.guild.id, rule_number))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Rule Removed",
                        f"Rule #{rule_number} has been removed.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "list":
                cur = await db.execute("""
                    SELECT rule_number, rule_text FROM server_rules
                    WHERE guild_id=? ORDER BY rule_number
                """, (interaction.guild.id,))
                rules_list = await cur.fetchall()
                
                if not rules_list:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "📜 Server Rules",
                            "No rules have been set yet.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                rules_text = "\n".join([f"**{num}.** {text}" for num, text in rules_list])
                embed = obsidian_embed(
                    "📜 Server Rules",
                    rules_text,
                    color=discord.Color.blue(),
                    client=interaction.client,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
