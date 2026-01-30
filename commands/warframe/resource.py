"""Warframe resource farming guide command."""
import discord
from discord import app_commands
from typing import Optional, List, Tuple

from utils import obsidian_embed

# Discord max 25 fields per embed
RESOURCES_PER_PAGE = 15


class ResourcePageButton(discord.ui.Button):
    """Prev/Next button for resource pagination."""

    def __init__(self, label: str, action: str, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: ResourcePaginationView = self.view
        if self.action == "prev" and view.current_page > 0:
            view.current_page -= 1
        elif self.action == "next" and view.current_page < view.total_pages - 1:
            view.current_page += 1
        else:
            return await interaction.response.defer()
        await view.update_message(interaction)


class ResourcePaginationView(discord.ui.View):
    """Pagination view for all-resources embed."""

    def __init__(self, pages: List[List[Tuple[str, str, bool]]], total_resources: int, client):
        super().__init__(timeout=300)
        self.pages = pages
        self.total_pages = len(pages)
        self.current_page = 0
        self.total_resources = total_resources
        self.client = client
        self._add_buttons()

    def _add_buttons(self):
        self.clear_items()
        if self.total_pages <= 1:
            return
        self.add_item(ResourcePageButton("◀️ Previous", "prev", disabled=(self.current_page == 0)))
        self.add_item(ResourcePageButton("Next ▶️", "next", disabled=(self.current_page >= self.total_pages - 1)))

    def _embed_for_page(self, page: int) -> discord.Embed:
        base_desc = f"Farming locations and tips for **{self.total_resources}** resources. Use `/resource <name>` for full details."
        if self.total_pages > 1:
            base_desc += f"\n\n**Page {page + 1} of {self.total_pages}**"
        return obsidian_embed(
            "🔍 Resource Farming Guide (All Resources)",
            base_desc,
            color=discord.Color.blue(),
            fields=self.pages[page],
            client=self.client,
        )

    async def update_message(self, interaction: discord.Interaction):
        self._add_buttons()
        embed = self._embed_for_page(self.current_page)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages} • {self.total_resources} resources")
        try:
            if interaction.response.is_done():
                await interaction.message.edit(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                await interaction.message.edit(embed=embed, view=self)
            except Exception:
                pass

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
        
        # Show farms for ALL resources when no resource specified or "all" (paginated)
        show_all = not resource or not resource.strip() or resource.strip().lower() == "all"
        if show_all:
            sorted_keys = sorted(RESOURCE_DATA.keys())
            all_fields: List[Tuple[str, str, bool]] = []
            for key in sorted_keys:
                data = RESOURCE_DATA[key]
                locs = data["best_locations"]
                loc_line = "\n".join(locs[:3]) if len(locs) >= 3 else "\n".join(locs)
                tip_short = data["tips"][:180] + "…" if len(data["tips"]) > 180 else data["tips"]
                value = f"{loc_line}\n\n💡 {tip_short}\n⭐ {data['rarity']}"
                if len(value) > 1020:
                    value = value[:1017] + "…"
                all_fields.append((f"🔍 {data['name']}", value, False))
            # Split into pages (RESOURCES_PER_PAGE per page, max 25 fields per embed)
            pages: List[List[Tuple[str, str, bool]]] = []
            for i in range(0, len(all_fields), RESOURCES_PER_PAGE):
                pages.append(all_fields[i : i + RESOURCES_PER_PAGE])
            view = ResourcePaginationView(pages, len(RESOURCE_DATA), interaction.client)
            embed = view._embed_for_page(0)
            embed.set_footer(text=f"Page 1/{view.total_pages} • {view.total_resources} resources")
            await interaction.followup.send(embed=embed, view=view)
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
