"""Warframe resource farming guide command."""
import discord
from discord import app_commands
from typing import Optional

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
    "hexenon": {
        "name": "Hexenon",
        "best_locations": [
            "**Jupiter** - Io (Defense) - Best location",
            "**Jupiter** - Ganymede (Survival) - Good alternative",
            "**Jupiter** - Cameria (Survival) - High level",
            "**Jupiter** - Any Corpus mission - Only drops here"
        ],
        "tips": "Jupiter only. Io defense is fastest. Use Nekros and break containers.",
        "rarity": "Uncommon"
    },
    "carbides": {
        "name": "Carbides",
        "best_locations": [
            "**Kuva Fortress** - Any mission - Only source",
            "**Kuva Fortress** - Survival - Best for farming",
            "**Kuva Fortress** - Exterminate - Quick runs",
            "**Kuva Siphon/Flood** - While farming Kuva"
        ],
        "tips": "Kuva Fortress only. Survival or endless missions for bulk. Nekros helps.",
        "rarity": "Uncommon"
    },
    "cubic diodes": {
        "name": "Cubic Diodes",
        "best_locations": [
            "**Plains of Eidolon** - Bounties and mining",
            "**Plains of Eidolon** - Free roam containers",
            "**Cetus** - Bounty rewards - Tier 2–3",
            "**Plains** - Incursions and caches"
        ],
        "tips": "Eidolon only. Bounties and mining are best. Break containers in free roam.",
        "rarity": "Uncommon"
    },
    "void traces": {
        "name": "Void Traces",
        "best_locations": [
            "**Void Fissures** - Any fissure mission - Only source",
            "**Capture/Exterminate fissures** - Fastest runs",
            "**Endless fissures** - More traces per run (scaling)",
            "**Radshare groups** - Farm relics and traces together"
        ],
        "tips": "Only from fissure missions. Complete the 10 reactant. Boosters and Smeeta stack.",
        "rarity": "Special"
    },
    "kuva": {
        "name": "Kuva",
        "best_locations": [
            "**Kuva Siphon** - Daily mission - Reliable",
            "**Kuva Flood** - Highest amount per run",
            "**Kuva Fortress** - Survival (Kuva Survival) - Endless",
            "**Steel Path** - Kuva Siphon/Flood - Bonus"
        ],
        "tips": "Siphon/Flood are main sources. Use the correct operator amp to destroy braids. Resource booster doubles.",
        "rarity": "Special"
    },
    "synthula": {
        "name": "Synthula",
        "best_locations": [
            "**Index** - High index rounds - Rare drop",
            "**Nezha Prime** - Farm in Index while farming credits",
            "**Profit-Taker** - Orb Vallis - Possible drop",
            "**Simaris** - Some synthesis targets"
        ],
        "tips": "Rare. Index is the most reliable. High risk/reward rounds.",
        "rarity": "Rare"
    },
    "entrati lanthorn": {
        "name": "Entrati Lanthorn",
        "best_locations": [
            "**Zariman** - Any mission - Only source",
            "**Zariman** - Exterminate - Fast runs",
            "**Zariman** - Void Armageddon - Good rate",
            "**Zariman** - Break containers and lockers"
        ],
        "tips": "Zariman only. Break every container. Thief's Wit helps. Rare drop.",
        "rarity": "Rare"
    },
    "thrax plasm": {
        "name": "Thrax Plasm",
        "best_locations": [
            "**Zariman** - Void Armageddon - Best source",
            "**Zariman** - Void Flood - Good amount",
            "**Zariman** - Cascade - Thrax spawn",
            "**Steel Path Zariman** - Higher drop rate"
        ],
        "tips": "Kill Thrax units (ghost form). Armageddon and Flood are best. Operator/amp damage.",
        "rarity": "Rare"
    },
}


def setup(bot, group=None):
    """Register the resource command."""
    command_decorator = group.command(name="resource", description="Get farming information for Warframe resources.") if group else bot.tree.command(name="resource", description="Get farming information for Warframe resources.")
    
    @command_decorator
    @app_commands.describe(resource="Resource name (e.g. orokin cell). Leave empty to show farms for all resources.")
    async def resource(interaction: discord.Interaction, resource: Optional[str] = None):
        """Show resource farming guide for one resource or all resources."""
        await interaction.response.defer()
        
        # Show farms for ALL resources when no resource specified or "all"
        show_all = not resource or not resource.strip() or resource.strip().lower() == "all"
        if show_all:
            # One field per resource; Discord max 25 fields per embed
            MAX_FIELDS = 25
            sorted_keys = sorted(RESOURCE_DATA.keys())
            all_fields = []
            for key in sorted_keys:
                data = RESOURCE_DATA[key]
                locs = data["best_locations"]
                loc_line = "\n".join(locs[:3]) if len(locs) >= 3 else "\n".join(locs)
                tip_short = data["tips"][:180] + "…" if len(data["tips"]) > 180 else data["tips"]
                value = f"{loc_line}\n\n💡 {tip_short}\n⭐ {data['rarity']}"
                if len(value) > 1020:
                    value = value[:1017] + "…"
                all_fields.append((f"🔍 {data['name']}", value, False))
            # Send first embed (up to 25 fields)
            first_batch = all_fields[:MAX_FIELDS]
            embed = obsidian_embed(
                "🔍 Resource Farming Guide (All Resources)",
                f"Farming locations and tips for **{len(RESOURCE_DATA)}** resources. Use `/resource <name>` for full details on one resource.",
                color=discord.Color.blue(),
                fields=first_batch,
                client=interaction.client,
            )
            await interaction.followup.send(embed=embed)
            # Second embed if more than 25 resources
            if len(all_fields) > MAX_FIELDS:
                second_batch = all_fields[MAX_FIELDS:]
                embed2 = obsidian_embed(
                    "🔍 Resource Farming Guide (continued)",
                    f"Resources **{MAX_FIELDS + 1}**–**{len(RESOURCE_DATA)}** of {len(RESOURCE_DATA)}.",
                    color=discord.Color.blue(),
                    fields=second_batch,
                    client=interaction.client,
                )
                await interaction.followup.send(embed=embed2)
            return
        
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
                    f"Resource '{resource}' not found.\n\n**Available resources:**\n{resource_list}\n\nUse `/resource` with no argument to see farms for all resources, or `/resource <name>` for full details.",
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
