"""Self-assignable roles command."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed, is_mod
from database import get_self_assignable_roles, get_self_assignable_categories, add_self_assignable_role, remove_self_assignable_role


def setup(bot, group=None):
    """Register the roles commands."""
    
    command_decorator = group.command(name="roles", description="View and manage self-assignable roles.") if group else bot.tree.command(name="roles", description="View and manage self-assignable roles.")
    
    @command_decorator
    @app_commands.describe(action="Action to perform", role="Role to add/remove", category="Category name")
    async def roles(interaction: discord.Interaction, action: str = "list", role: Optional[discord.Role] = None, category: Optional[str] = None):
        """View or manage self-assignable roles."""
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
            # List all self-assignable roles
            roles_list = await get_self_assignable_roles(interaction.guild.id)
            categories = await get_self_assignable_categories(interaction.guild.id)
            
            if not roles_list:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Self-Assignable Roles",
                        "No self-assignable roles have been configured.\n\nModerators can add roles using `/roles add`.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Group by category
            if categories:
                desc = ""
                for cat in categories:
                    cat_roles = [r for r in roles_list if r["category"] == cat]
                    if cat_roles:
                        desc += f"**{cat}**\n"
                        for r in cat_roles:
                            role_obj = interaction.guild.get_role(r["role_id"])
                            if role_obj:
                                desc += f"• {role_obj.mention}\n"
                        desc += "\n"
                
                # Roles without category
                uncategorized = [r for r in roles_list if not r["category"]]
                if uncategorized:
                    desc += "**Other**\n"
                    for r in uncategorized:
                        role_obj = interaction.guild.get_role(r["role_id"])
                        if role_obj:
                            desc += f"• {role_obj.mention}\n"
            else:
                desc = ""
                for r in roles_list:
                    role_obj = interaction.guild.get_role(r["role_id"])
                    if role_obj:
                        desc += f"• {role_obj.mention}\n"
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "📋 Self-Assignable Roles",
                    desc or "No roles found.",
                    color=discord.Color.blue(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "add":
            # Add a self-assignable role (mods only)
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        "Sorry, but you are not an Administrator in this server.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if not role:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Role",
                        "Please specify a role to add.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await add_self_assignable_role(interaction.guild.id, role.id, category)
            
            category_text = f' in category "{category}"' if category else ''
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Role Added",
                    f"{role.mention} has been added as a self-assignable role{category_text}.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        elif action.lower() == "remove":
            # Remove a self-assignable role (mods only)
            if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        "Sorry, but you are not an Administrator in this server.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            if not role:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Missing Role",
                        "Please specify a role to remove.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            await remove_self_assignable_role(interaction.guild.id, role.id)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Role Removed",
                    f"{role.mention} has been removed from self-assignable roles.",
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
    
    command_decorator = group.command(name="role", description="Assign or remove a self-assignable role.") if group else bot.tree.command(name="role", description="Assign or remove a self-assignable role.")
    
    @command_decorator
    @app_commands.describe(action="Assign or remove the role", role="The role to assign/remove")
    async def role(interaction: discord.Interaction, action: str, role: discord.Role):
        """Assign or remove a self-assignable role."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
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
        
        # Check if role is self-assignable
        roles_list = await get_self_assignable_roles(interaction.guild.id)
        role_data = next((r for r in roles_list if r["role_id"] == role.id), None)
        
        if not role_data:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Not Self-Assignable",
                    f"{role.mention} is not a self-assignable role. Use `/roles list` to see available roles.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Check max roles limit if set
        if role_data["max_roles"]:
            user_roles = [r for r in interaction.user.roles if r.id != interaction.guild.id]  # Exclude @everyone
            if len(user_roles) >= role_data["max_roles"]:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Role Limit Reached",
                        f"You have reached the maximum number of roles ({role_data['max_roles']}). Remove a role first.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        if action.lower() in ["add", "assign", "give"]:
            if role in interaction.user.roles:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Have Role",
                        f"You already have {role.mention}.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            try:
                await interaction.user.add_roles(role, reason="Self-assigned role")
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Role Assigned",
                        f"You have been given {role.mention}.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        "I don't have permission to assign this role.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        elif action.lower() in ["remove", "rem", "take"]:
            if role not in interaction.user.roles:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Don't Have Role",
                        f"You don't have {role.mention}.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            try:
                await interaction.user.remove_roles(role, reason="Self-removed role")
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "✅ Role Removed",
                        f"{role.mention} has been removed from you.",
                        color=discord.Color.green(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Permission Denied",
                        "I don't have permission to remove this role.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
        
        else:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Action",
                    "Valid actions: `add`, `assign`, `give`, `remove`, `rem`, `take`",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
