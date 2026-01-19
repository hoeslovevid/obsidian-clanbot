"""Clan Dojo Tracker commands."""
import discord
from discord import app_commands
from typing import Optional
import json

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


def setup(bot, group=None):
    """Register dojo tracker commands."""
    
    command_decorator = group.command(name="dojo_research", description="Track clan dojo research progress.") if group else bot.tree.command(name="dojo_research", description="Track clan dojo research progress.")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        research_name="Name of the research",
        research_type="Type of research (weapon/room/decoration/etc)",
        required_resources="Required resources (JSON format or comma-separated)",
        current_resources="Current resources (JSON format or comma-separated)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="update", value="update"),
        app_commands.Choice(name="complete", value="complete"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    async def dojo_research(interaction: discord.Interaction, action: str, research_name: Optional[str] = None, research_type: Optional[str] = None, required_resources: Optional[str] = None, current_resources: Optional[str] = None):
        """Manage dojo research tracking."""
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
                if not research_name or not research_type:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Parameters",
                            "Please provide research name and type.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    INSERT INTO dojo_research (guild_id, research_name, research_type, required_resources, current_resources, status, started_at)
                    VALUES (?, ?, ?, ?, ?, 'in_progress', ?)
                """, (interaction.guild.id, research_name, research_type, required_resources or "{}", current_resources or "{}", now_utc().isoformat()))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Research Added",
                        f"**{research_name}** ({research_type}) has been added to tracking.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "update":
                if not research_name:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Research Name",
                            "Please provide the research name to update.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                updates = []
                params = []
                
                if current_resources:
                    updates.append("current_resources = ?")
                    params.append(current_resources)
                
                if not updates:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ No Updates",
                            "Please provide current_resources to update.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                params.append(interaction.guild.id)
                params.append(research_name)
                
                await db.execute(f"""
                    UPDATE dojo_research SET {', '.join(updates)}
                    WHERE guild_id=? AND research_name=?
                """, tuple(params))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Research Updated",
                        f"**{research_name}** has been updated.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "complete":
                if not research_name:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Research Name",
                            "Please provide the research name to complete.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    UPDATE dojo_research SET status='completed', completed_at=?
                    WHERE guild_id=? AND research_name=?
                """, (now_utc().isoformat(), interaction.guild.id, research_name))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Research Completed",
                        f"**{research_name}** has been marked as completed.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "list":
                cur = await db.execute("""
                    SELECT research_name, research_type, status, current_resources, required_resources
                    FROM dojo_research WHERE guild_id=? ORDER BY status, research_name
                """, (interaction.guild.id,))
                research_list = await cur.fetchall()
                
                if not research_list:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "🔬 Dojo Research",
                            "No research is being tracked. Use `/dojo_research add` to add research.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                research_text = ""
                for name, rtype, status, current, required in research_list:
                    status_emoji = "✅" if status == "completed" else "🔄"
                    research_text += f"{status_emoji} **{name}** ({rtype}) - {status}\n"
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "🔬 Dojo Research",
                        research_text,
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "remove":
                if not research_name:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Research Name",
                            "Please provide the research name to remove.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                cur = await db.execute("""
                    DELETE FROM dojo_research WHERE guild_id=? AND research_name=?
                """, (interaction.guild.id, research_name))
                await db.commit()
                
                if cur.rowcount == 0:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Not Found",
                            f"Research '{research_name}' not found.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Research Removed",
                        f"**{research_name}** has been removed from tracking.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
    
    command_decorator = group.command(name="dojo_decoration", description="Track dojo decorations.") if group else bot.tree.command(name="dojo_decoration", description="Track dojo decorations.")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        decoration_name="Name of the decoration",
        room_location="Location/room of the decoration",
        quantity="Quantity (for add)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    async def dojo_decoration(interaction: discord.Interaction, action: str, decoration_name: Optional[str] = None, room_location: Optional[str] = None, quantity: Optional[int] = 1):
        """Manage dojo decorations."""
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
        
        async with aiosqlite.connect(DB_PATH) as db:
            if action == "add":
                if not decoration_name:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Decoration Name",
                            "Please provide the decoration name.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await db.execute("""
                    INSERT INTO dojo_decorations (guild_id, decoration_name, room_location, quantity, added_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (interaction.guild.id, decoration_name, room_location, quantity, now_utc().isoformat()))
                await db.commit()
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Decoration Added",
                        f"**{decoration_name}** (x{quantity}) has been added to tracking.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "list":
                cur = await db.execute("""
                    SELECT decoration_name, room_location, quantity FROM dojo_decorations
                    WHERE guild_id=? ORDER BY decoration_name
                """, (interaction.guild.id,))
                decorations = await cur.fetchall()
                
                if not decorations:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "🎨 Dojo Decorations",
                            "No decorations are being tracked.",
                            color=discord.Color.blue(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                deco_text = "\n".join([
                    f"• **{name}** x{quant}" + (f" - {room}" if room else "")
                    for name, room, quant in decorations
                ])
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "🎨 Dojo Decorations",
                        deco_text,
                        color=discord.Color.blue(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            elif action == "remove":
                if not decoration_name:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Missing Decoration Name",
                            "Please provide the decoration name to remove.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                cur = await db.execute("""
                    DELETE FROM dojo_decorations WHERE guild_id=? AND decoration_name=?
                """, (interaction.guild.id, decoration_name))
                await db.commit()
                
                if cur.rowcount == 0:
                    return await interaction.followup.send(
                        embed=obsidian_embed(
                            "❌ Not Found",
                            f"Decoration '{decoration_name}' not found.",
                            color=discord.Color.red(),
                            client=interaction.client,
                        ),
                        ephemeral=True
                    )
                
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Decoration Removed",
                        f"**{decoration_name}** has been removed from tracking.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
