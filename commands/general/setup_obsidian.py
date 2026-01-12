"""Setup Obsidian command."""
import asyncio
import discord

from utils import obsidian_embed, is_mod

# Track in-flight setup commands to prevent duplicates
_setup_in_progress = set()


def setup(bot):
    """Register the setup_obsidian command."""
    @bot.tree.command(name="setup_obsidian", description="Create/ensure core channels and post Obsidian panels (mods only).")
    async def setup_obsidian(interaction: discord.Interaction):
        # Import bot-specific functions inside the command to avoid circular imports
        from bot import ensure_core_channels, ensure_join_to_create_channel, ComplaintPanel
        from bot import CREATE_VC_NAME, TEMP_VC_CATEGORY_NAME, VOICE_PANEL_CHANNEL_NAME
        
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            return await interaction.response.send_message("Obsidian Inheritors only.", ephemeral=True)

        # Prevent duplicate execution
        interaction_key = f"{interaction.guild.id}:{interaction.channel.id}:{interaction.user.id}"
        if interaction_key in _setup_in_progress:
            if not interaction.response.is_done():
                await interaction.response.send_message("Setup already in progress...", ephemeral=True)
            return
        
        try:
            _setup_in_progress.add(interaction_key)
            
            # Respond first, then do the work
            await interaction.response.defer(ephemeral=True)

            await ensure_core_channels(interaction.guild)
            await ensure_join_to_create_channel(interaction.guild)

            # Post panels where command is run
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

            await interaction.channel.send(
                embed=obsidian_embed(
                    "Dojo Comms",
                    f"Join **{CREATE_VC_NAME}** inside **{TEMP_VC_CATEGORY_NAME}** to forge a temporary cell channel.\n"
                    f"A control panel will appear in **#{VOICE_PANEL_CHANNEL_NAME}** for the squad owner.",
                )
            )

            await interaction.channel.send(
                embed=obsidian_embed(
                    "Ops Board",
                    "Create events with **/event_create**.\n"
                    "Times support natural phrasing (e.g., `tomorrow 8pm`).\n"
                    "RSVP buttons + reminder included.",
                )
            )

            await interaction.followup.send("Obsidian systems deployed.", ephemeral=True)
        finally:
            await asyncio.sleep(1)
            _setup_in_progress.discard(interaction_key)
