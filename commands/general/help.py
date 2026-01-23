"""Help command with interactive group selection."""
import discord
from discord import app_commands

from utils import obsidian_embed, is_mod, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE


class HelpSelectView(discord.ui.View):
    """View with select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.is_user_mod = is_user_mod
        self.add_item(HelpSelect(bot, is_user_mod))
    
    async def on_timeout(self):
        """Disable the view when it times out."""
        for item in self.children:
            item.disabled = True


class HelpSelect(discord.ui.Select):
    """Select menu for choosing command groups."""
    
    def __init__(self, bot, is_user_mod: bool):
        self.bot = bot
        self.is_user_mod = is_user_mod
        
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
        
        # Build command list for this group
        commands_list = []
        for cmd in group.commands:
            if isinstance(cmd, app_commands.Command):
                # Get command description
                desc = cmd.description or "No description"
                # Truncate if too long
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                commands_list.append(f"• `/{group.name} {cmd.name}` - {desc}")
            elif isinstance(cmd, app_commands.Group):
                # Nested group (shouldn't happen, but handle it)
                commands_list.append(f"• `/{group.name} {cmd.name}` - {cmd.description or 'Group'}")
        
        if not commands_list:
            commands_text = "No commands available in this group."
        else:
            # Join commands, but ensure we don't exceed field value limit (1024 chars)
            commands_text = "\n".join(commands_list)
            if len(commands_text) > 1024:
                # Truncate to fit
                truncated = []
                current_length = 0
                for cmd in commands_list:
                    if current_length + len(cmd) + 1 > 1020:  # Leave room for "..."
                        truncated.append(f"... and {len(commands_list) - len(truncated)} more commands")
                        break
                    truncated.append(cmd)
                    current_length += len(cmd) + 1
                commands_text = "\n".join(truncated)
        
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
        group_desc = group_descriptions.get(selected_group, group.description or "Commands")
        
        embed = obsidian_embed(
            f"📋 {group_name} Commands",
            group_desc,
            color=discord.Color.blurple(),
            fields=[("Commands", commands_text, False)],
            client=interaction.client,
        )
        
        # Add footer with command count
        embed.set_footer(text=f"{len(group.commands)} command(s) in this group")
        
        await interaction.response.edit_message(embed=embed, view=self.view)


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
