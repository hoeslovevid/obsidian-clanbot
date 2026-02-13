"""Setup Docket command - posts the complaint/help request embed."""
import asyncio
import discord

from utils import obsidian_embed, is_mod

# Track in-flight setup commands to prevent duplicates
_docket_setup_in_progress = set()


def setup(bot, group=None):
    """Register the setup_docket command."""
    command_decorator = group.command(name="setup_docket", description="Post the complaints/help request panel (mods only).") if group else bot.tree.command(name="setup_docket", description="Post the complaints/help request panel (mods only).")
    
    @command_decorator
    async def setup_docket(interaction: discord.Interaction):
        # Import bot-specific functions inside the command to avoid circular imports
        from bot import resolve_channel_id, ComplaintPanel
        from bot import COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Sorry, but you are not an Administrator in this server.", ephemeral=True)

        # Prevent duplicate execution
        interaction_key = f"{interaction.guild.id}:{interaction.channel.id}:{interaction.user.id}"
        if interaction_key in _docket_setup_in_progress:
            if not interaction.response.is_done():
                await interaction.response.send_message("Setup already in progress...", ephemeral=True)
            return
        
        try:
            _docket_setup_in_progress.add(interaction_key)
            
            # Respond first, then do the work
            await interaction.response.defer(ephemeral=True)

            # Get complaints channel (prefer guild_settings from setup_obsidian)
            from database import get_configured_channel_id
            complaints_channel_id = await get_configured_channel_id(interaction.guild.id, "complaints_channel_id")
            if not complaints_channel_id:
                complaints_channel_id = await resolve_channel_id(interaction.guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)
            
            if not complaints_channel_id or complaints_channel_id == 0:
                return await interaction.followup.send(
                    "Complaints channel not configured. Use `/general setup_obsidian` to configure channels, then run this command again.",
                    ephemeral=True,
                )
                
            # Verify the channel exists and is accessible
            complaints_channel = interaction.guild.get_channel(complaints_channel_id)
            if not isinstance(complaints_channel, discord.TextChannel):
                return await interaction.followup.send(
                    f"Complaints channel (ID: {complaints_channel_id}) not found or not a text channel. Use `/general setup_obsidian` to reconfigure.",
                    ephemeral=True,
                )

            # Post the complaints panel (mod runs command in the channel where they want it)
            await interaction.channel.send(
                embed=obsidian_embed(
                    "Complaints",
                    "File a complaint or help request.\n\n"
                    "• Provide details & evidence links\n"
                    "• False reports may be actioned\n"
                    "• You will receive DM updates",
                    color=discord.Color.red(),
                ),
                view=ComplaintPanel(),
            )

            await interaction.followup.send("Complaints panel deployed.", ephemeral=True)
        finally:
            await asyncio.sleep(1)
            _docket_setup_in_progress.discard(interaction_key)
