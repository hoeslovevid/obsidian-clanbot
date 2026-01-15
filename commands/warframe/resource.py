"""Warframe resource farming guide command."""
import discord
from discord import app_commands

from utils import obsidian_embed

# Resource farming data
RESOURCE_DATA = {
    "orokin cell": {
        "name": "Orokin Cell",
        "best_locations": [
            "**Saturn** - Helene (Defense) - High drop rate from Eximus units",
            "**Saturn** - Piscinas (Survival) - Good for farming while leveling",
            "**Ceres** - Draco (Interception) - Good alternative",
            "**Deimos** - Cambion Drift bounties - Guaranteed rewards"
        ],
        "tips": "Eximus units have higher drop rates. Use Nekros or Hydroid with Pilfering Swarm for better chances.",
        "rarity": "Uncommon"
    },
    "neural sensor": {
        "name": "Neural Sensor",
        "best_locations": [
            "**Jupiter** - Io (Defense) - Best early game location",
            "**Jupiter** - Ganymede (Survival) - Good for extended farming",
            "**Jupiter** - Alad V (Assassination) - Guaranteed drop",
            "**Jupiter** - Cameria (Survival) - High level alternative"
        ],
        "tips": "Alad V assassination guarantees 1-2 per run. Use resource boosters for better yields.",
        "rarity": "Uncommon"
    },
    "neurodes": {
        "name": "Neurodes",
        "best_locations": [
            "**Earth** - Lua (Crossfire) - Good early game",
            "**Eris** - Akkad (Defense) - Popular farming spot",
            "**Deimos** - Cambion Drift - High drop rate",
            "**Plains of Eidolon** - Bounties and mining"
        ],
        "tips": "Deimos has the highest drop rate. Use Nekros with Desecrate for better chances.",
        "rarity": "Uncommon"
    },
    "morphics": {
        "name": "Morphics",
        "best_locations": [
            "**Mars** - War (Assassination) - Guaranteed drop",
            "**Mars** - Ara (Survival) - Good for farming",
            "**Phobos** - Any mission - Decent drop rate",
            "**Pluto** - Outer Terminus (Defense) - High level option"
        ],
        "tips": "War assassination on Mars is the fastest guaranteed method. Resource boosters help significantly.",
        "rarity": "Common"
    },
    "gallium": {
        "name": "Gallium",
        "best_locations": [
            "**Mars** - War (Assassination) - Guaranteed drop",
            "**Mars** - Ara (Survival) - Good farming spot",
            "**Uranus** - Any mission - Higher drop rate",
            "**Plains of Eidolon** - Mining"
        ],
        "tips": "Mars assassination is fastest. Uranus missions have better drop rates for bulk farming.",
        "rarity": "Uncommon"
    },
    "control module": {
        "name": "Control Module",
        "best_locations": [
            "**Neptune** - Any mission - Common drop",
            "**Void** - Any mission - Very common",
            "**Europa** - Any mission - Good alternative",
            "**Void Fissures** - Guaranteed from containers"
        ],
        "tips": "Void missions have the highest drop rate. Break all containers for extra chances.",
        "rarity": "Common"
    },
    "argon crystal": {
        "name": "Argon Crystal",
        "best_locations": [
            "**Void** - Any mission - Only drops here",
            "**Void** - Teshub (Exterminate) - Fast runs",
            "**Void** - Hepit (Capture) - Quickest method",
            "**Void Fissures** - Good while farming relics"
        ],
        "tips": "Argon Crystals decay after 24 hours! Farm only what you need. Break all containers.",
        "rarity": "Uncommon"
    },
    "tellurium": {
        "name": "Tellurium",
        "best_locations": [
            "**Uranus** - Ophelia (Survival) - Best location",
            "**Uranus** - Assur (Survival) - Good alternative",
            "**Archwing missions** - Low drop rate",
            "**Railjack** - Grineer missions - Decent rate"
        ],
        "tips": "Ophelia on Uranus is the best spot. Use Nekros and stay underwater for better spawns.",
        "rarity": "Rare"
    },
    "nitain extract": {
        "name": "Nitain Extract",
        "best_locations": [
            "**Nightwave** - Cred offerings - Most reliable",
            "**Ghoul Purge** - Bounties (rare)",
            "**Gift of the Lotus** - Alerts (rare)",
            "**Sabotage caches** - Very rare"
        ],
        "tips": "Nightwave is the primary source. Save Nightwave credits for Nitain. Very limited availability.",
        "rarity": "Rare"
    },
    "cryotic": {
        "name": "Cryotic",
        "best_locations": [
            "**Excavation missions** - Only source",
            "**Earth** - Everest (Excavation) - Early game",
            "**Hieracon, Pluto** - Best for farming",
            "**Tikal, Earth** - Good alternative"
        ],
        "tips": "Excavation is the only way to get Cryotic. Hieracon on Pluto gives the most per extractor.",
        "rarity": "Common"
    },
    "oxium": {
        "name": "Oxium",
        "best_locations": [
            "**Corpus missions** - Only from Oxium Ospreys",
            "**Jupiter** - Io (Defense) - Best early game",
            "**Galatea, Neptune** - High level farming",
            "**Baal, Europa** - Good alternative"
        ],
        "tips": "Only Oxium Ospreys drop it. They self-destruct, so kill them quickly. Use Nekros for more drops.",
        "rarity": "Uncommon"
    },
    "plastids": {
        "name": "Plastids",
        "best_locations": [
            "**Saturn** - Piscinas (Survival) - Best location",
            "**Uranus** - Ophelia (Survival) - Good alternative",
            "**Phobos** - Any mission - Early game",
            "**Eris** - Any mission - High level"
        ],
        "tips": "Piscinas on Saturn is the best spot. Use Nekros and stay for 20+ minutes for best results.",
        "rarity": "Uncommon"
    },
    "polymer bundle": {
        "name": "Polymer Bundle",
        "best_locations": [
            "**Venus** - Any mission - Early game",
            "**Uranus** - Ophelia (Survival) - Best location",
            "**Mercury** - Any mission - Very early",
            "**Mars** - Any mission - Decent rate"
        ],
        "tips": "Ophelia on Uranus is the best. Break all containers. Very common resource.",
        "rarity": "Common"
    },
    "rubedo": {
        "name": "Rubedo",
        "best_locations": [
            "**Earth** - Any mission - Early game",
            "**Mars** - Any mission - Good rate",
            "**Europa** - Any mission - Higher level",
            "**Void** - Any mission - Best rate"
        ],
        "tips": "Very common resource. Void missions have the highest drop rate. Break containers for extra.",
        "rarity": "Common"
    },
    "alloy plate": {
        "name": "Alloy Plate",
        "best_locations": [
            "**Venus** - Any mission - Early game",
            "**Ceres** - Any mission - Best location",
            "**Jupiter** - Any mission - Good alternative",
            "**Plains of Eidolon** - Mining"
        ],
        "tips": "Ceres has the highest drop rate. Very common resource needed in large quantities.",
        "rarity": "Common"
    },
    "ferrite": {
        "name": "Ferrite",
        "best_locations": [
            "**Mercury** - Any mission - Early game",
            "**Earth** - Any mission - Good rate",
            "**Mars** - Any mission - Decent",
            "**Void** - Any mission - Best rate"
        ],
        "tips": "Very common resource. Void missions have the highest drop rate. Break all containers.",
        "rarity": "Common"
    },
    "nano spores": {
        "name": "Nano Spores",
        "best_locations": [
            "**Saturn** - Piscinas (Survival) - Best location",
            "**Eris** - Akkad (Defense) - Popular spot",
            "**Deimos** - Any mission - High rate",
            "**Derelict** - Any mission - Very high"
        ],
        "tips": "Very common resource. Deimos and Derelict have the highest drop rates.",
        "rarity": "Common"
    },
    "salvage": {
        "name": "Salvage",
        "best_locations": [
            "**Mars** - Any mission - Early game",
            "**Jupiter** - Any mission - Good rate",
            "**Europa** - Any mission - Higher level",
            "**Railjack** - Grineer missions"
        ],
        "tips": "Common resource. Break all containers. Railjack missions give good amounts.",
        "rarity": "Common"
    },
    "circuits": {
        "name": "Circuits",
        "best_locations": [
            "**Venus** - Any mission - Early game",
            "**Jupiter** - Any mission - Best location",
            "**Europa** - Any mission - Good alternative",
            "**Corpus missions** - Generally higher rate"
        ],
        "tips": "Jupiter has the highest drop rate. Corpus missions are best for farming.",
        "rarity": "Common"
    },
}


def setup(bot):
    """Register the resource command."""
    @bot.tree.command(name="resource", description="Get farming information for a Warframe resource.")
    @app_commands.describe(resource="The resource name (e.g., orokin cell, neural sensor)")
    async def resource(interaction: discord.Interaction, resource: str):
        """Show resource farming guide."""
        await interaction.response.defer()
        
        resource_lower = resource.lower().strip()
        
        # Try to find matching resource
        resource_info = None
        for key, data in RESOURCE_DATA.items():
            if key in resource_lower or resource_lower in key:
                resource_info = data
                break
        
        if not resource_info:
            # Show list of available resources
            resource_list = ", ".join([f"`{name}`" for name in sorted(RESOURCE_DATA.keys())])
            return await interaction.followup.send(
                embed=obsidian_embed(
                    "❌ Resource Not Found",
                    f"Resource '{resource}' not found.\n\n**Available resources:**\n{resource_list}\n\nUse `/resource <name>` to get farming info.",
                    color=discord.Color.red(),
                    client=interaction.client,
                )
            )
        
        # Build embed with farming info
        locations_text = "\n".join(resource_info["best_locations"])
        
        fields = [
            ("📍 Best Locations", locations_text, False),
            ("💡 Tips", resource_info["tips"], False),
            ("⭐ Rarity", resource_info["rarity"], True),
        ]
        
        embed = obsidian_embed(
            f"🔍 {resource_info['name']} Farming Guide",
            f"Where and how to farm **{resource_info['name']}** efficiently",
            color=discord.Color.blue(),
            fields=fields,
            client=interaction.client,
        )
        
        await interaction.followup.send(embed=embed)
