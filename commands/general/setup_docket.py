"""Setup Docket command - posts the complaint/help request embed."""
import asyncio
import discord

from utils import obsidian_embed, is_mod

# Track in-flight setup commands to prevent duplicates
_docket_setup_in_progress = set()


def setup(bot):
    """Register the setup_docket command."""
    @bot.tree.command(name="setup_docket", description="Post the Obsidian Docket (complaint/help request) panel (mods only).")
    async def setup_docket(interaction: discord.Interaction):
        # Import bot-specific functions inside the command to avoid circular imports
        from bot import resolve_channel_id, ComplaintPanel
        from bot import COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

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

            # Only ensure the complaints channel (not all channels)
            await resolve_channel_id(interaction.guild, "complaints_channel_id", COMPLAINTS_CHANNEL_ID, COMPLAINTS_CHANNEL_NAME)

            # Post the Docket panel
            await interaction.channel.send(
                embed=obsidian_embed(
                    "Obsidian Docket",
                    "Seal a docket entry for the Inheritors.\n\n"
                    "• Provide details & evidence links\n"
                    "• False reports may be actioned\n"
                    "• You will receive DM docket updates",
                    color=discord.Color.red(),
                ),
                view=ComplaintPanel(),
            )

            await interaction.followup.send("Obsidian Docket deployed.", ephemeral=True)
        finally:
            await asyncio.sleep(1)
            _docket_setup_in_progress.discard(interaction_key)
