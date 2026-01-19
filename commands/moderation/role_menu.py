"""Role menu commands."""
import discord
from discord import app_commands
from typing import Optional, List
from discord.ui import View, Button, Select

from utils import obsidian_embed, is_mod
from database import DB_PATH, now_utc
import aiosqlite


class RoleMenuView(View):
    """View for role menu selection."""
    def __init__(self, menu_id: int, options: List[dict]):
        super().__init__(timeout=None)
        self.menu_id = menu_id
        self.options = options
        
        # Create select menu
        select_options = []
        for opt in options:
            select_options.append(discord.SelectOption(
                label=opt['label'],
                value=str(opt['role_id']),
                emoji=opt.get('emoji'),
                description=opt.get('description', '')[:100]
            ))
        
        select = Select(
            placeholder="Select a role...",
            options=select_options,
            custom_id=f"role_menu_{menu_id}"
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction: discord.Interaction):
        """Handle role selection."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        
        selected_role_id = int(interaction.data['values'][0])
        role = interaction.guild.get_role(selected_role_id)
        
        if not role:
            return await interaction.response.send_message("Role not found.", ephemeral=True)
        
        # Check max roles limit
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT max_roles FROM role_menus WHERE id=?
            """, (self.menu_id,))
            row = await cur.fetchone()
            max_roles = row[0] if row and row[0] else None
        
        if max_roles:
            # Count user's roles from this menu
            cur = await db.execute("""
                SELECT COUNT(*) FROM role_menu_options
                WHERE menu_id=? AND role_id IN (SELECT role_id FROM role_menu_options WHERE menu_id=?)
            """, (self.menu_id, self.menu_id))
            # Actually, let's just count roles the user has from this menu
            user_menu_roles = [r for r in interaction.user.roles if r.id in [opt['role_id'] for opt in self.options]]
            if len(user_menu_roles) >= max_roles and role not in user_menu_roles:
                return await interaction.response.send_message(
                    f"You can only have {max_roles} role(s) from this menu. Remove one first.",
                    ephemeral=True
                )
        
        # Toggle role
        if role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role, reason="Role menu")
                await interaction.response.send_message(f"Removed {role.mention}", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to remove this role.", ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role, reason="Role menu")
                await interaction.response.send_message(f"Added {role.mention}", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to add this role.", ephemeral=True)


def setup(bot):
    """Register role menu commands."""
    global bot_instance
    bot_instance = bot
    
    @bot.tree.command(name="role_menu", description="Create an interactive role selection menu (moderators only).")
    @app_commands.describe(
        title="Title of the role menu",
        description="Description of the role menu",
        max_roles="Maximum number of roles a user can select (optional)"
    )
    async def role_menu(interaction: discord.Interaction, title: str, description: Optional[str] = None, max_roles: Optional[int] = None):
        """Create a role menu."""
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
        
        await interaction.response.send_message(
            embed=obsidian_embed(
                "✅ Role Menu Created",
                "The role menu has been created. Use `/role_menu_add` to add roles to it.",
                color=discord.Color.green(),
                client=interaction.client,
            ),
            ephemeral=True
        )
        
        # Create embed for role menu
        embed = obsidian_embed(
            title,
            description or "Select a role from the dropdown below.",
            color=discord.Color.blue(),
            client=interaction.client,
        )
        
        # Store menu in database (without options yet)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO role_menus (guild_id, channel_id, message_id, title, description, max_roles)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (interaction.guild.id, interaction.channel.id, 0, title, description, max_roles))
            await db.commit()
            
            cur = await db.execute("SELECT last_insert_rowid()")
            menu_id = (await cur.fetchone())[0]
        
        # Send placeholder message (will be updated when roles are added)
        view = RoleMenuView(menu_id, [], bot)
        message = await interaction.channel.send(embed=embed, view=view)
        
        # Update message_id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE role_menus SET message_id=? WHERE id=?
            """, (message.id, menu_id))
            await db.commit()
        
        bot.add_view(view)
    
    @bot.tree.command(name="role_menu_add", description="Add a role to a role menu (moderators only).")
    @app_commands.describe(
        message_id="The role menu message ID",
        role="Role to add",
        label="Label for the role (optional)",
        emoji="Emoji for the role (optional)",
        role_description="Description for the role option (optional)"
    )
    async def role_menu_add(interaction: discord.Interaction, message_id: str, role: discord.Role, label: Optional[str] = None, emoji: Optional[str] = None, role_description: Optional[str] = None):
        """Add a role to a menu."""
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
        
        try:
            msg_id = int(message_id)
        except ValueError:
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Invalid Message ID",
                    "Please provide a valid message ID.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Find menu
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT id, title, description, max_roles FROM role_menus
                WHERE guild_id=? AND message_id=?
            """, (interaction.guild.id, msg_id))
            row = await cur.fetchone()
            
            if not row:
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "❌ Menu Not Found",
                        "No role menu found with that message ID.",
                        color=discord.Color.red(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            menu_id, title, description, max_roles = row
            
            # Check if role already added
            cur = await db.execute("""
                SELECT 1 FROM role_menu_options WHERE menu_id=? AND role_id=?
            """, (menu_id, role.id))
            if await cur.fetchone():
                return await interaction.followup.send(
                    embed=obsidian_embed(
                        "ℹ️ Already Added",
                        f"{role.mention} is already in this menu.",
                        color=discord.Color.orange(),
                        client=interaction.client,
                    ),
                    ephemeral=True
                )
            
            # Add role option
            await db.execute("""
                INSERT INTO role_menu_options (menu_id, role_id, label, emoji, description)
                VALUES (?, ?, ?, ?, ?)
            """, (menu_id, role.id, label or role.name, emoji, role_description))
            await db.commit()
            
            # Get all options
            cur = await db.execute("""
                SELECT role_id, label, emoji, description FROM role_menu_options
                WHERE menu_id=? ORDER BY id
            """, (menu_id,))
            options = [{'role_id': r[0], 'label': r[1], 'emoji': r[2], 'description': r[3]} for r in await cur.fetchall()]
        
            # Update message with new view
        try:
            channel = interaction.channel
            message = await channel.fetch_message(msg_id)
            
            view = RoleMenuView(menu_id, options, bot)
            await message.edit(view=view)
            bot.add_view(view)
            
            await interaction.followup.send(
                embed=obsidian_embed(
                    "✅ Role Added",
                    f"{role.mention} has been added to the role menu.",
                    color=discord.Color.green(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        except discord.NotFound:
            await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Message Not Found",
                    "Could not find the role menu message.",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
