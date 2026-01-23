"""Help command with interactive group selection."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE


class PageButton(discord.ui.Button):
    """Button for pagination."""
    
    def __init__(self, label: str, action: str, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.action = action
    
    async def callback(self, interaction: discord.Interaction):
        """Handle page navigation."""
        view: HelpSelectView = self.view
        if not view.current_group:
            return await interaction.response.send_message("No group selected.", ephemeral=True)
        
        total_commands = len(view.current_group.commands)
        total_pages = (total_commands + view.commands_per_page - 1) // view.commands_per_page
        
        if self.action == "prev" and view.current_page > 0:
            view.current_page -= 1
        elif self.action == "next" and view.current_page < total_pages - 1:
            view.current_page += 1
        else:
            return await interaction.response.defer()
        
        # Update embed with new page
        select_item = next((item for item in view.children if isinstance(item, HelpSelect)), None)
        if select_item:
            await select_item.update_embed(interaction, view.current_group, view.current_page)


class PageSelect(discord.ui.Select):
    """Select menu for jumping to a specific page."""
    
    def __init__(self, total_pages: int, current_page: int):
        options = []
        for i in range(total_pages):
            options.append(
                discord.SelectOption(
                    label=f"Page {i + 1}",
                    value=str(i),
                    default=(i == current_page)
                )
            )
        
        super().__init__(
            placeholder=f"Jump to page...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle page jump."""
        view: HelpSelectView = self.view
        if not view.current_group:
            return await interaction.response.send_message("No group selected.", ephemeral=True)
        
        page = int(self.values[0])
        view.current_page = page
        
        # Update embed with new page
        select_item = next((item for item in view.children if isinstance(item, HelpSelect)), None)
        if select_item:
            await select_item.update_embed(interaction, view.current_group, view.current_page)


class HelpSelectView(discord.ui.View):
    """View with select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.is_user_mod = is_user_mod
        self.current_group = None
        self.current_page = 0
        self.commands_per_page = 15  # Commands per page
        self.add_item(HelpSelect(bot, is_user_mod, self))
    
    async def on_timeout(self):
        """Disable the view when it times out."""
        for item in self.children:
            item.disabled = True
    
    def update_pagination_buttons(self):
        """Update pagination buttons based on current state."""
        # Remove existing pagination buttons
        pagination_items = [item for item in self.children if isinstance(item, (PageButton, PageSelect))]
        for item in pagination_items:
            self.remove_item(item)
        
        # Only add pagination if we have a group with multiple pages
        if self.current_group:
            total_commands = len(self.current_group.commands)
            total_pages = (total_commands + self.commands_per_page - 1) // self.commands_per_page
            
            if total_pages > 1:
                # Add page navigation buttons
                if self.current_page > 0:
                    self.add_item(PageButton("◀️ Previous", "prev", disabled=False))
                else:
                    self.add_item(PageButton("◀️ Previous", "prev", disabled=True))
                
                # Add page selector (max 25 options, so limit if needed)
                if total_pages <= 25:
                    self.add_item(PageSelect(total_pages, self.current_page))
                
                if self.current_page < total_pages - 1:
                    self.add_item(PageButton("Next ▶️", "next", disabled=False))
                else:
                    self.add_item(PageButton("Next ▶️", "next", disabled=True))


class HelpSelect(discord.ui.Select):
    """Select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool, parent_view):
        self.bot = bot
        self.is_user_mod = is_user_mod
        self.parent_view = parent_view
        
        # Get available groups from bot
        available_groups = {}
        for cmd in bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group):
                available_groups[cmd.name] = cmd
        
        # Define all possible groups with their emojis and descriptions
        group_definitions = {
            "general": ("General", "General bot commands", "📋"),
            "economy": ("Economy", "Economy and coin management", "💰"),
            "warframe": ("Warframe", "Warframe game information", "🎮"),
            "community": ("Community", "Community features", "👥"),
            "trading": ("Trading", "Trading commands", "💼"),
            "mod": ("Moderation", "Moderation and server management", "🛡️"),
            "giveaways": ("Giveaways", "Giveaway commands", "🎁"),
            "updates": ("Updates", "Update log commands", "📝"),
            "music": ("Music", "Music commands", "🎵"),
        }
        
        # Only add options for groups that actually exist
        options = []
        for group_name, (label, description, emoji) in group_definitions.items():
            if group_name in available_groups:
                options.append(
                    discord.SelectOption(
                        label=label,
                        description=description,
                        emoji=emoji,
                        value=group_name
                    )
                )
        
        super().__init__(
            placeholder="Select a command group to view...",
            options=options,
            min_values=1,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle group selection."""
        selected_group = self.values[0]
        
        # Get the group from bot's command tree
        # Use guild=None to get all commands (works for both global and guild-specific)
        group = None
        for cmd in self.bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group) and cmd.name == selected_group:
                group = cmd
                break
        
        if not group:
            # Fallback: try with the interaction's guild if it exists
            if interaction.guild:
                for cmd in self.bot.tree.get_commands(guild=interaction.guild):
                    if isinstance(cmd, app_commands.Group) and cmd.name == selected_group:
                        group = cmd
                        break
        
        if not group:
            return await interaction.response.send_message(
                f"Group '{selected_group}' not found. Please try again.",
                ephemeral=True
            )
        
        # Store current group and reset page
        self.parent_view.current_group = group
        self.parent_view.current_page = 0
        
        # Build and display the page
        await self.update_embed(interaction, group, 0)
    
    async def update_embed(self, interaction: discord.Interaction, group: app_commands.Group, page: int):
        """Update the embed with commands for the specified page."""
        # Build command list for this group
        commands_list = []
        for cmd in group.commands:
            if isinstance(cmd, app_commands.Command):
                # Get command description
                desc = cmd.description or "No description"
                # Truncate description if too long (keep command name + description under reasonable length)
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                # Format: command name - description
                cmd_text = f"• `/{group.name} {cmd.name}` - {desc}"
                commands_list.append(cmd_text)
            elif isinstance(cmd, app_commands.Group):
                # Nested group (shouldn't happen, but handle it)
                commands_list.append(f"• `/{group.name} {cmd.name}` - {cmd.description or 'Group'}")
        
        if not commands_list:
            commands_text = "No commands available in this group."
            total_pages = 1
        else:
            # Calculate pagination
            total_pages = (len(commands_list) + self.parent_view.commands_per_page - 1) // self.parent_view.commands_per_page
            start_idx = page * self.parent_view.commands_per_page
            end_idx = min(start_idx + self.parent_view.commands_per_page, len(commands_list))
            
            # Get commands for this page
            page_commands = commands_list[start_idx:end_idx]
            
            # Build text, ensuring we don't exceed 1024 chars
            commands_text = ""
            for cmd in page_commands:
                # Check if adding this command would exceed limit
                test_text = commands_text + cmd + "\n" if commands_text else cmd + "\n"
                if len(test_text) > 1020:  # Leave some room
                    break
                commands_text = test_text
            
            # Remove trailing newline
            commands_text = commands_text.rstrip()
            
            # If we couldn't fit all commands on this page, indicate there are more
            if end_idx < len(commands_list):
                remaining = len(commands_list) - end_idx
                if len(commands_text) + len(f"\n... {remaining} more (use pagination)") <= 1024:
                    commands_text += f"\n... {remaining} more (use pagination)"
        
        # Group descriptions
        group_descriptions = {
            "general": "General bot commands and utilities",
            "economy": "💰 Economy and coin management commands",
            "warframe": "🎮 Warframe game information and tracking",
            "community": "👥 Community features and interactions",
            "trading": "💼 Trading and marketplace commands",
            "mod": "🛡️ Moderation and server management (moderators only)",
            "giveaways": "🎁 Giveaway management commands",
            "updates": "📝 Bot update log commands (moderators only)",
            "music": "🎵 Music and audio commands"
        }
        
        # Build embed
        group_name = group.name.title()
        group_desc = group_descriptions.get(group.name, group.description or "Commands")
        
        # Add page info to description if multiple pages
        if total_pages > 1:
            group_desc += f"\n\n**Page {page + 1} of {total_pages}**"
        
        embed = obsidian_embed(
            f"📋 {group_name} Commands",
            group_desc,
            color=discord.Color.blurple(),
            fields=[("Commands", commands_text, False)],
            client=interaction.client,
        )
        
        # Add footer with command count
        footer_text = f"{len(group.commands)} command(s) in this group"
        if total_pages > 1:
            footer_text += f" • Page {page + 1}/{total_pages}"
        embed.set_footer(text=footer_text)
        
        # Update pagination buttons
        self.parent_view.update_pagination_buttons()
        
        # Update the message
        if interaction.response.is_done():
            # Use followup to edit if response is already done
            try:
                await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self.parent_view)
            except:
                # Fallback: try editing the original message
                await interaction.message.edit(embed=embed, view=self.parent_view)
        else:
            await interaction.response.edit_message(embed=embed, view=self.parent_view)


def setup(bot, group=None):
    """Register the help command."""
    command_decorator = group.command(name="help", description="Get help and information about all bot commands.") if group else bot.tree.command(name="help", description="Get help and information about all bot commands.")
    
    @command_decorator
    async def help_command(interaction: discord.Interaction):
        """Display an interactive help embed with command groups."""
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # Get all groups
        # Use guild=None to get all commands (works for both global and guild-specific)
        groups = []
        for cmd in bot.tree.get_commands(guild=None):
            if isinstance(cmd, app_commands.Group):
                groups.append(cmd)
        
        # Build initial embed
        desc = "Select a command group from the dropdown below to view all commands in that group.\n\n"
        desc += "**Available Groups:**\n"
        
        group_info = {
            "general": ("📋 General", "General bot commands"),
            "economy": ("💰 Economy", "Economy and coin management"),
            "warframe": ("🎮 Warframe", "Warframe game information"),
            "community": ("👥 Community", "Community features"),
            "trading": ("💼 Trading", "Trading commands"),
            "mod": ("🛡️ Moderation", "Moderation and server management"),
            "giveaways": ("🎁 Giveaways", "Giveaway commands"),
            "updates": ("📝 Updates", "Update log commands"),
            "music": ("🎵 Music", "Music commands"),
        }
        
        for group in groups:
            if group.name in group_info:
                emoji_name, group_desc = group_info[group.name]
                desc += f"{emoji_name} **{group.name.title()}** - {len(group.commands)} command(s)\n"
        
        # Add feature info
        desc += "\n**💬 Features:**\n"
        desc += "• Join-to-Create Voice Channels\n"
        desc += "• Obsidian Docket (complaint system)\n"
        desc += "• Voice Channel Controls"
        if ECONOMY_ENABLED:
            desc += f"\n• Economy: {COINS_PER_MESSAGE} coins/msg ({MESSAGE_COOLDOWN_SECONDS}s cooldown)"
            desc += f"\n• Voice: {COINS_PER_MINUTE_VOICE} coins/minute"
        
        embed = obsidian_embed(
            "Obsidian Clan Bot • Command Reference",
            desc,
            color=discord.Color.blurple(),
            client=interaction.client,
        )
        
        # Create view with select menu
        view = HelpSelectView(bot, is_user_mod)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
