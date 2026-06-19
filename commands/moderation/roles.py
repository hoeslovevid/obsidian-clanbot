"""Self-assignable roles command."""
import asyncio
import discord
from discord import app_commands
from typing import Optional

from core.utils import obsidian_embed, is_mod
from database import get_self_assignable_roles_and_categories, add_self_assignable_role, remove_self_assignable_role


def setup(bot, group=None):
    """Register the roles commands."""
    
    command_decorator = group.command(name="list", description="View and manage self-assignable roles.") if group else bot.tree.command(name="list", description="View and manage self-assignable roles.")
    
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
            roles_list, categories = await get_self_assignable_roles_and_categories(interaction.guild.id)
            
            if not roles_list:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "📋 Self-Assignable Roles",
                        "No self-assignable roles have been configured.\n\nModerators can add roles using `/mod role_tools list add`.",
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
            
            embed = obsidian_embed(
                "📋 Self-Assignable Roles",
                desc or "No roles found.",
                color=discord.Color.blue(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                footer=f"{len(roles_list)} role(s) • Use /mod role_tools assign to get roles",
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
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
            embed = obsidian_embed(
                "✅ Role Added",
                f"{role.mention} has been added as a self-assignable role{category_text}.",
                color=discord.Color.green(),
                thumbnail=interaction.guild.icon.url if interaction.guild.icon else None,
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        
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
    
    mass_add_decorator = (
        group.command(name="mass_add", description="Add a role to all members (or to members who have a specific role).")
        if group
        else bot.tree.command(name="mass_add", description="Mass-add a role to members.")
    )

    @mass_add_decorator
    @app_commands.describe(
        role="Role to add to members",
        filter_role="Only add to members who already have this role (optional)",
    )
    async def mass_add(
        interaction: discord.Interaction,
        role: discord.Role,
        filter_role: Optional[discord.Role] = None,
    ):
        """Add a role to all (or filtered) members. Mod-only."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Permission Denied", "Administrator only.", category="error", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Role Too High", "That role is above my highest role — I can't assign it.", category="error", client=interaction.client),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        candidates = [
            m for m in interaction.guild.members
            if not m.bot and role not in m.roles and (filter_role is None or filter_role in m.roles)
        ]

        if not candidates:
            return await interaction.followup.send(
                embed=obsidian_embed("ℹ️ Nothing To Do", "All eligible members already have that role.", category="general", client=interaction.client),
                ephemeral=True,
            )

        scope = f"members with **{filter_role.name}**" if filter_role else "all members"
        await interaction.followup.send(
            embed=obsidian_embed(
                "⏳ Mass Role Add",
                f"Adding {role.mention} to **{len(candidates)}** {scope}…\nThis may take a while.",
                category="moderation",
                client=interaction.client,
            ),
            ephemeral=True,
        )

        success, failed = 0, 0
        for member in candidates:
            try:
                await member.add_roles(role, reason=f"Mass add by {interaction.user}")
                success += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1
            await asyncio.sleep(0.5)  # respect rate limits

        await interaction.followup.send(
            embed=obsidian_embed(
                "✅ Mass Role Add Complete",
                f"Added {role.mention} to **{success}** member(s)."
                + (f"\n⚠️ Failed for **{failed}** member(s) (likely missing permissions)." if failed else ""),
                category="moderation",
                client=interaction.client,
            ),
            ephemeral=True,
        )
        try:
            from core.audit import log_audit
            bot_ref = getattr(interaction.client, "bot", interaction.client)
            await log_audit(
                interaction.guild.id,
                "mass_add_role",
                interaction.user.id,
                target_id=role.id,
                target_type="role",
                details=f"+{success} members",
                bot=bot_ref,
            )
        except Exception:
            pass

    mass_remove_decorator = (
        group.command(name="mass_remove", description="Remove a role from all members who have it.")
        if group
        else bot.tree.command(name="mass_remove", description="Mass-remove a role from members.")
    )

    @mass_remove_decorator
    @app_commands.describe(
        role="Role to remove from members",
        filter_role="Only remove from members who also have this second role (optional)",
    )
    async def mass_remove(
        interaction: discord.Interaction,
        role: discord.Role,
        filter_role: Optional[discord.Role] = None,
    ):
        """Remove a role from all (or filtered) members. Mod-only."""
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Permission Denied", "Administrator only.", category="error", client=interaction.client),
                ephemeral=True,
            )
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                embed=obsidian_embed("❌ Role Too High", "That role is above my highest role — I can't remove it.", category="error", client=interaction.client),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        candidates = [
            m for m in interaction.guild.members
            if not m.bot and role in m.roles and (filter_role is None or filter_role in m.roles)
        ]

        if not candidates:
            return await interaction.followup.send(
                embed=obsidian_embed("ℹ️ Nothing To Do", "No eligible members have that role.", category="general", client=interaction.client),
                ephemeral=True,
            )

        scope = f"members with **{filter_role.name}**" if filter_role else "all members"

        from views import ConfirmView
        from core.embed_templates import confirm_embed

        confirm = confirm_embed(
            "⚠️ Confirm Mass Role Remove",
            f"Remove {role.mention} from **{len(candidates)}** {scope}?\nThis cannot be undone in one click.",
            client=interaction.client,
        )

        async def on_confirm(btn_interaction: discord.Interaction, confirmed: bool):
            if not confirmed:
                return await btn_interaction.followup.send("Cancelled.", ephemeral=True)
            if btn_interaction.user.id != interaction.user.id:
                return await btn_interaction.followup.send(
                    "Only the person who started this can confirm.", ephemeral=True
                )
            await btn_interaction.followup.send(
                embed=obsidian_embed(
                    "⏳ Mass Role Remove",
                    f"Removing {role.mention} from **{len(candidates)}** {scope}…\nThis may take a while.",
                    category="moderation",
                    client=interaction.client,
                ),
                ephemeral=True,
            )
            success, failed = 0, 0
            for member in candidates:
                try:
                    await member.remove_roles(role, reason=f"Mass remove by {interaction.user}")
                    success += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
                await asyncio.sleep(0.5)
            await btn_interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Mass Role Remove Complete",
                    f"Removed {role.mention} from **{success}** member(s)."
                    + (f"\n⚠️ Failed for **{failed}** member(s)." if failed else ""),
                    category="moderation",
                    client=btn_interaction.client,
                ),
                ephemeral=True,
            )
            try:
                from core.audit import log_audit
                bot_ref = getattr(btn_interaction.client, "bot", btn_interaction.client)
                await log_audit(
                    interaction.guild.id,
                    "mass_remove_role",
                    interaction.user.id,
                    target_id=role.id,
                    target_type="role",
                    details=f"-{success} members",
                    bot=bot_ref,
                )
            except Exception:
                pass

        view = ConfirmView(on_confirm)
        await interaction.followup.send(embed=confirm, view=view, ephemeral=True)

    command_decorator = group.command(name="assign", description="Assign or remove a self-assignable role.") if group else bot.tree.command(name="assign", description="Assign or remove a self-assignable role.")
    
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
        
        roles_list, _ = await get_self_assignable_roles_and_categories(interaction.guild.id)
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
                embed = obsidian_embed(
                    "✅ Role Assigned",
                    f"You have been given {role.mention}.",
                    color=discord.Color.green(),
                    thumbnail=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                    footer="Use /mod role_tools assign remove to remove",
                    client=interaction.client,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
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
