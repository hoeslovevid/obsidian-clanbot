"""Help command."""
import discord

from utils import obsidian_embed, is_mod, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE


def setup(bot, group=None):
    """Register the help command."""
    command_decorator = group.command(name="help", description="Get help and information about all bot commands.") if group else bot.tree.command(name="help", description="Get help and information about all bot commands.")
    
    @command_decorator
    async def help_command(interaction: discord.Interaction):
        """Display a help embed with all available commands and their usage."""
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        # Build fields instead of one long description
        fields = []
        
        # Event Commands
        event_cmd = "• `/event_create` - Create an Ops event with RSVP\n"
        event_cmd += "  Usage: `/event_create title:<name> when:<time> description:<details>`\n"
        event_cmd += "  Example: `/event_create title:Steel Path when:tomorrow 8pm`"
        fields.append(("📅 Events", event_cmd, False))
        
        # Help & Complaint Commands
        help_cmd = "• `/request_help` - Create or check help request\n"
        help_cmd += "  Create: `/request_help category:<type> details:<info>`\n"
        help_cmd += "  Check: `/request_help case_id:<OBS-...>`\n"
        help_cmd += "• `/submit_complaint` - Add info to your case\n"
        help_cmd += "  Usage: `/submit_complaint case_id:<OBS-...> details:<info>`"
        fields.append(("🩸 Help & Complaints", help_cmd, False))
        
        # Economy Commands
        economy_cmd = "• `/daily` - Claim daily coin reward\n"
        economy_cmd += "• `/balance` - Check your coin balance\n"
        economy_cmd += "• `/leaderboard [limit]` - View top earners\n"
        economy_cmd += "• `/transfer user:<@user> amount:<number>` - Transfer coins"
        fields.append(("💰 Economy", economy_cmd, False))
        
        # Trading Commands
        trading_cmd = "• `/trade` - Post WTS/WTB listing\n"
        trading_cmd += "  Example: `/trade listing_type:WTS item:Mesa Prime Set price:200`\n"
        trading_cmd += "• `/trade_price item:<name>` - Check market prices\n"
        trading_cmd += "• `/trade_search` - Search active listings\n"
        trading_cmd += "• `/trade_list` - View your listings"
        fields.append(("💼 Trading", trading_cmd, False))
        
        # Suggestion Commands
        suggest_cmd = "• `/suggest suggestion:<text>` - Submit a suggestion"
        if is_user_mod:
            suggest_cmd += "\n• `/suggestions` - Manage suggestions (mods only)"
        fields.append(("💡 Suggestions", suggest_cmd, False))
        
        # Application Commands
        app_cmd = "• `/application` - Start clan application"
        if is_user_mod:
            app_cmd += "\n• `/application_setup` - Configure system (mods)\n"
            app_cmd += "• `/manage_applications` - Manage apps (mods)"
        fields.append(("📝 Applications", app_cmd, False))
        
        # Moderator Commands
        if is_user_mod:
            mod_cmd = "• `/setup_obsidian` - Set up channels and panels\n"
            mod_cmd += "• `/setup_docket` - Post complaint panel\n"
            mod_cmd += "• `/purge amount:<1-100>` - Clear messages"
            fields.append(("⚙️ Moderation", mod_cmd, False))
            
            update_cmd = "• `/update_log_setup` - Configure update channel\n"
            update_cmd += "• `/update_log` - Post bot update\n"
            update_cmd += "• `/force_version_update` - Force post update"
            fields.append(("🔔 Updates", update_cmd, False))
        
        # Other Features
        features = "• Join-to-Create Voice Channels\n"
        features += "• Obsidian Docket (complaint system)\n"
        features += "• Voice Channel Controls"
        if ECONOMY_ENABLED:
            features += f"\n• Economy: {COINS_PER_MESSAGE} coins/msg ({MESSAGE_COOLDOWN_SECONDS}s cooldown)"
            features += f"\n• Voice: {COINS_PER_MINUTE_VOICE} coins/minute"
        fields.append(("💬 Features", features, False))
        
        # Notes
        notes = "• Event times: natural language (e.g., `tomorrow 8pm`)\n"
        notes += "• Case IDs sent via DM when filing reports\n"
        notes += "• DM updates on complaint status (if enabled)"
        fields.append(("ℹ️ Notes", notes, False))
        
        embed = obsidian_embed(
            "Obsidian Clan Bot • Command Reference",
            "Use these commands to interact with the bot:",
            color=discord.Color.blurple(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
