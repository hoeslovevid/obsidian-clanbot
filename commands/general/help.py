"""Help command."""
import discord

from utils import obsidian_embed, is_mod, ECONOMY_ENABLED, COINS_PER_MESSAGE, MESSAGE_COOLDOWN_SECONDS, COINS_PER_MINUTE_VOICE


def setup(bot):
    """Register the help command."""
    
    @bot.tree.command(name="help", description="Get help and information about all bot commands.")
    async def help_command(interaction: discord.Interaction):
        """Display a help embed with all available commands and their usage."""
        is_user_mod = isinstance(interaction.user, discord.Member) and is_mod(interaction.user)
        
        desc = "**Obsidian Clan Bot Commands**\n\n"
        desc += "Use these commands to interact with the bot:\n\n"
        
        # Public commands
        desc += "**📅 Event Commands**\n"
        desc += "• `/event_create` - Create an Ops event with RSVP and reminders\n"
        desc += "  └ Usage: `/event_create title:<name> when:<time> description:<details> [role_ping:<@role>]`\n"
        desc += "  └ Example: `/event_create title:Steel Path when:tomorrow 8pm description:Running ESO rotations`\n\n"
        
        desc += "**🩸 Help & Complaint Commands**\n"
        desc += "• `/request_help` - Create a new help request OR check status of existing case\n"
        desc += "  └ To create: `/request_help category:<type> details:<info> [evidence:<link>]`\n"
        desc += "  └ To check status: `/request_help case_id:<OBS-...>`\n"
        desc += "  └ Example (new): `/request_help category:harassment details:Someone was being rude`\n"
        desc += "  └ Example (check): `/request_help case_id:OBS-1234567890-1234`\n\n"
        
        desc += "• `/submit_complaint` - Add additional information to your complaint/help request\n"
        desc += "  └ Usage: `/submit_complaint case_id:<OBS-...> details:<additional info>`\n"
        desc += "  └ Example: `/submit_complaint case_id:OBS-1234567890-1234 details:Here are screenshots`\n\n"
        
        # Mod-only commands
        if is_user_mod:
            desc += "**⚙️ Moderator Commands**\n"
            desc += "• `/setup_obsidian` - Set up channels and post Dojo Comms & Ops Board panels\n"
            desc += "  └ Creates voice panel and events channels, posts Dojo Comms and Ops Board embeds\n\n"
            
            desc += "• `/setup_docket` - Post the Obsidian Docket (complaint/help request) panel\n"
            desc += "  └ Creates complaints channel and posts the Docket embed with complaint button\n\n"
            
            desc += "• `/purge` - Clear messages from the current channel\n"
            desc += "  └ Usage: `/purge amount:<1-100> or 'all'`\n"
            desc += "  └ Example: `/purge amount:50` or `/purge amount:all`\n"
            desc += "  └ Note: Pinned messages are never deleted\n\n"
        else:
            desc += "**⚙️ Moderator Commands**\n"
            desc += "• `/setup_obsidian` - (Mods only) Set up channels and panels\n"
            desc += "• `/setup_docket` - (Mods only) Post complaint/help request panel\n"
            desc += "• `/purge` - (Mods only) Clear messages from channels\n\n"
        
        desc += "**💰 Economy Commands**\n"
        desc += "• `/daily` - Claim your daily coin reward (once per day)\n"
        desc += "• `/balance` - Check your coin balance\n"
        desc += "• `/leaderboard [limit]` - View top coin earners (default: 10, max: 25)\n"
        desc += "• `/transfer user:<@user> amount:<number>` - Transfer coins to another user\n"
        desc += "  └ Example: `/transfer user:@friend amount:100`\n\n"
        
        desc += "**💡 Suggestion Commands**\n"
        desc += "• `/suggest` - Submit a suggestion for the bot (new commands, features, improvements, etc.)\n"
        desc += "  └ Usage: `/suggest suggestion:<your suggestion>`\n"
        desc += "  └ Example: `/suggest suggestion:Add a command to check daily login rewards`\n"
        if is_user_mod:
            desc += "• `/suggestions` - View and manage suggestions (moderators only)\n"
            desc += "  └ Usage: `/suggestions [status:<all/pending/approved/rejected/implemented>] [limit:<number>]`\n"
        desc += "\n"
        
        desc += "**📝 Application Commands**\n"
        desc += "• `/application` - Start a clan application (use in the designated application channel)\n"
        desc += "  └ You'll receive questions via DM. Answer them to complete your application.\n"
        if is_user_mod:
            desc += "• `/application_setup` - Configure the application system (moderators only)\n"
            desc += "  └ Set the application channel and manage questions\n"
            desc += "• `/manage_applications` - View and manage applications (moderators only)\n"
            desc += "  └ Usage: `/manage_applications [status:<all/in_progress/pending/approved/rejected>] [limit:<number>]`\n"
        desc += "\n"
        
        if is_user_mod:
            desc += "**🔔 Update Log Commands**\n"
            desc += "• `/update_log_setup` - Configure the update log channel (moderators only)\n"
            desc += "  └ Usage: `/update_log_setup channel:#channel` or `/update_log_setup` (to disable)\n"
            desc += "• `/update_log` - Post a bot update log (moderators only)\n"
            desc += "  └ Usage: `/update_log title:<title> description:<description> [version:<version>]`\n"
            desc += "  └ Example: `/update_log title:New Command Added description:Added /application command for clan recruitment`\n"
            desc += "• `/force_version_update` - Force post the most recent bot update to Discord (moderators only)\n"
            desc += "  └ Usage: `/force_version_update`\n"
            desc += "  └ Note: This will post the current bot version and changelog to the update log channel\n"
            desc += "\n"
        
        desc += "**💼 Trading Commands**\n"
        desc += "• `/trade` - Post a WTS (Want To Sell) or WTB (Want To Buy) listing\n"
        desc += "  └ Usage: `/trade listing_type:<WTS/WTB> item:<item name> [price:<platinum>] [quantity:<number>] [description:<details>]`\n"
        desc += "  └ Example: `/trade listing_type:WTS item:Mesa Prime Set price:200 quantity:1`\n"
        desc += "• `/trade_price` - Check current market prices for an item\n"
        desc += "  └ Usage: `/trade_price item:<item name> [platform:<pc/xbox/ps4/switch>]`\n"
        desc += "  └ Example: `/trade_price item:Primed Continuity platform:pc`\n"
        desc += "• `/trade_search` - Search active trading listings\n"
        desc += "  └ Usage: `/trade_search [query:<search term>] [listing_type:<WTS/WTB>] [platform:<platform>]`\n"
        desc += "• `/trade_list` - View your active trading listings\n"
        if is_user_mod:
            desc += "• `/trade_setup` - Configure the trading channel (moderators only)\n"
        desc += "\n"
        
        desc += "**💬 Other Features**\n"
        desc += "• **Join-to-Create Voice Channels** - Join the trigger channel in Temp VCs to create your own squad channel\n"
        desc += "• **Obsidian Docket** - Use the button panel to file complaints (mods will review)\n"
        desc += "• **Voice Channel Controls** - Squad owners get control panels for their channels\n"
        if ECONOMY_ENABLED:
            desc += "• **Economy System** - Earn coins by chatting and being active in voice channels\n"
        desc += "\n"
        
        desc += "**ℹ️ Notes**\n"
        desc += "• Event times support natural language (e.g., `tomorrow 8pm`, `Jan 14 7:30pm`)\n"
        desc += "• Complaint case IDs are sent to you via DM when you file a report\n"
        desc += "• You'll receive DM updates on your complaint status (if DMs are enabled)\n"
        if ECONOMY_ENABLED:
            desc += f"• Earn {COINS_PER_MESSAGE} coins per message ({MESSAGE_COOLDOWN_SECONDS}s cooldown)\n"
            desc += f"• Earn {COINS_PER_MINUTE_VOICE} coins per minute in voice channels\n"
        
        embed = obsidian_embed(
            "Obsidian Clan Bot • Command Reference",
            desc,
            color=discord.Color.blurple(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
