"""Resource farming command - shows drop locations and best nodes."""
import discord
from discord import app_commands
from typing import Optional

from utils import obsidian_embed

# Common resource farming locations (simplified - could be expanded with full drop tables)
RESOURCE_LOCATIONS = {
    "neurodes": {
        "best_nodes": ["Earth - Lua (Crossfire)", "Eris - Akkad", "Deimos - Isolation Vaults"],
        "drop_rate": "Common",
        "notes": "Also drops from Sentients on Lua"
    },
    "neural_sensors": {
        "best_nodes": ["Jupiter - Alad V (Assassination)", "Jupiter - Io", "Jupiter - Ganymede"],
        "drop_rate": "Uncommon",
        "notes": "Jupiter is the primary source"
    },
    "orokin_cell": {
        "best_nodes": ["Saturn - Helene", "Saturn - Cassini", "Ceres - Draco"],
        "drop_rate": "Uncommon",
        "notes": "Saturn and Ceres are best sources"
    },
    "alloy_plate": {
        "best_nodes": ["Venus - Tessera", "Mars - Olympus", "Jupiter - Io"],
        "drop_rate": "Common",
        "notes": "Very common resource"
    },
    "circuits": {
        "best_nodes": ["Venus - Tessera", "Jupiter - Io", "Europa - Valac"],
        "drop_rate": "Common",
        "notes": "Early game resource"
    },
    "polymer_bundle": {
        "best_nodes": ["Venus - Tessera", "Uranus - Ophelia", "Mercury - Apollodorus"],
        "drop_rate": "Common",
        "notes": "Common resource"
    },
    "rubedo": {
        "best_nodes": ["Mars - Olympus", "Europa - Valac", "Pluto - Outer Terminus"],
        "drop_rate": "Common",
        "notes": "Common resource"
    },
    "ferrite": {
        "best_nodes": ["Mercury - Apollodorus", "Earth - Cambria", "Mars - Olympus"],
        "drop_rate": "Common",
        "notes": "Very common early resource"
    },
    "salvage": {
        "best_nodes": ["Mars - Olympus", "Jupiter - Io", "Europa - Valac"],
        "drop_rate": "Common",
        "notes": "Common resource"
    },
    "nanospores": {
        "best_nodes": ["Saturn - Helene", "Eris - Akkad", "Deimos - Isolation Vaults"],
        "drop_rate": "Common",
        "notes": "Very common resource"
    },
    "plastids": {
        "best_nodes": ["Saturn - Helene", "Uranus - Ophelia", "Phobos - Memphis"],
        "drop_rate": "Uncommon",
        "notes": "Mid-game resource"
    },
    "control_module": {
        "best_nodes": ["Europa - Valac", "Neptune - Laomedeia", "Void - Teshub"],
        "drop_rate": "Uncommon",
        "notes": "Void missions are good sources"
    },
    "gallium": {
        "best_nodes": ["Mars - Olympus", "Uranus - Ophelia", "Europa - Valac"],
        "drop_rate": "Uncommon",
        "notes": "Mid-game resource"
    },
    "morphics": {
        "best_nodes": ["Mars - Olympus", "Mercury - Apollodorus", "Pluto - Outer Terminus"],
        "drop_rate": "Uncommon",
        "notes": "Early-mid game resource"
    },
    "argon_crystal": {
        "best_nodes": ["Void - Teshub", "Void - Mot", "Void - Taranis"],
        "drop_rate": "Rare",
        "notes": "Only found in Void. Decays after 24 hours."
    },
    "tellurium": {
        "best_nodes": ["Uranus - Ophelia", "Kuva Fortress - Taveuni", "Archwing missions"],
        "drop_rate": "Rare",
        "notes": "Best from Archwing missions on Uranus"
    },
    "cryotic": {
        "best_nodes": ["Excavation missions", "Earth - Cambria", "Europa - Valac"],
        "drop_rate": "Mission-specific",
        "notes": "Only from Excavation missions"
    },
    "oxium": {
        "best_nodes": ["Jupiter - Io", "Europa - Valac", "Corpus missions"],
        "drop_rate": "Uncommon",
        "notes": "Drops from Oxium Ospreys (Corpus)"
    },
    "mutagen_sample": {
        "best_nodes": ["Eris - Akkad", "Deimos - Isolation Vaults", "Derelict missions"],
        "drop_rate": "Uncommon",
        "notes": "Infested missions are best"
    },
    "detonite_ampule": {
        "best_nodes": ["Grineer missions", "Earth - Cambria", "Mars - Olympus"],
        "drop_rate": "Uncommon",
        "notes": "Drops from Grineer enemies"
    },
    "fieldron_sample": {
        "best_nodes": ["Corpus missions", "Jupiter - Io", "Europa - Valac"],
        "drop_rate": "Uncommon",
        "notes": "Drops from Corpus enemies"
    },
}


def setup(bot):
    """Register the resource_farming command."""
    
    @bot.tree.command(name="resource_farming", description="Find the best locations to farm a specific resource.")
    @app_commands.describe(resource="The resource you want to farm")
    async def resource_farming(interaction: discord.Interaction, resource: str):
        """Show farming locations for a resource."""
        await interaction.response.defer(ephemeral=True)
        
        # Normalize resource name
        resource_lower = resource.lower().strip().replace(" ", "_")
        
        # Try exact match first
        resource_data = RESOURCE_LOCATIONS.get(resource_lower)
        
        # Try partial match if exact match fails
        if not resource_data:
            for key, data in RESOURCE_LOCATIONS.items():
                if resource_lower in key or key.replace("_", " ") in resource_lower:
                    resource_data = data
                    resource_lower = key
                    break
        
        if not resource_data:
            # List available resources
            available = ", ".join(sorted([r.replace("_", " ").title() for r in RESOURCE_LOCATIONS.keys()]))
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Resource Not Found",
                    f"Resource '{resource}' not found.\n\n**Available resources:**\n{available}",
                    color=discord.Color.red(),
                    client=interaction.client,
                ),
                ephemeral=True
            )
        
        # Build embed
        resource_name = resource_lower.replace("_", " ").title()
        desc = f"**Best Farming Nodes:**\n"
        for node in resource_data["best_nodes"]:
            desc += f"• {node}\n"
        
        desc += f"\n**Drop Rate:** {resource_data['drop_rate']}\n"
        if resource_data.get("notes"):
            desc += f"**Notes:** {resource_data['notes']}"
        
        embed = obsidian_embed(
            f"⛏️ Resource Farming: {resource_name}",
            desc,
            color=discord.Color.green(),
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
