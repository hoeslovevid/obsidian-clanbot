"""Level roles setup command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import add_level_role, remove_level_role, get_level_roles


def setup(bot, group=None):
    """Register the level_roles command."""
    
    command_decorator = group.command(name="level_roles", description="Configure roles that are automatically assigned at specific XP levels (mods only).") if group else bot.tree.command(name="level_roles", description="Configure roles that are automatically assigned at specific XP levels (mods only).")
    
    @command_decorator
    @app_commands.describe(
        action="Action to perform",
        level="XP level required",
        role="Role to assign at this level"
    )
    async def level_roles(
        interaction: discord.Interaction,
        action: str,
        level: Optional[int] = None,
        role: Optional[discord.Role] = None
    ):
        """Configure level roles."""
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
        
        if action.lower() == "list":
            # List all level roles
            level_roles_list = await get_level_roles(interaction.guild.id)
            
            if not level_roles_list:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Level Roles",
                        "No level roles have been configured.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            desc = ""
            for lr in sorted(level_roles_list, key=lambda x: x["level"]):
                role_obj = interaction.guild.get_role(lr["role_id"])
                if role_obj:
                    desc += f"**Level {lr['level']}** → {role_obj.mention}\n"
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Level Roles",
                    desc,
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "add":
            if not level or not role:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Parameters",
                        "Please specify both a level and a role.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if level < 1:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Invalid Level",
                        "Level must be at least 1.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await add_level_role(interaction.guild.id, level, role.id)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Level Role Added",
                    f"Users who reach level {level} will automatically receive {role.mention}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            if not level:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Level",
                        "Please specify the level to remove.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await remove_level_role(interaction.guild.id, level)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Level Role Removed",
                    f"Level {level} role has been removed.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `list`, `add`, `remove`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
