"""
Warframe API functions for fetching game data.
This module handles all Warframe World State API calls.
"""
import logging
from typing import Optional, Dict, Any, Tuple, List
import aiohttp  # type: ignore
import dateparser  # type: ignore
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def fetch_baro_data() -> Optional[Dict[str, Any]]:
    """Fetch Baro Ki'Teer data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/voidTrader", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching Baro data: {e}")
        return None


async def fetch_cycle_data(cycle_type: str) -> Optional[Dict[str, Any]]:
    """Fetch cycle data from Warframe World State API.
    
    Args:
        cycle_type: One of 'cetus', 'vallis', or 'cambion'
    
    Returns:
        Cycle data dict or None if error
    """
    endpoints = {
        'cetus': 'https://api.warframestat.us/pc/cetusCycle',
        'vallis': 'https://api.warframestat.us/pc/vallisCycle',
        'cambion': 'https://api.warframestat.us/pc/cambionCycle',
    }
    
    if cycle_type not in endpoints:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoints[cycle_type], timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status} for {cycle_type}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching {cycle_type} cycle data: {e}")
        return None


async def get_all_cycles() -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch all cycle data (Cetus, Fortuna, Deimos)."""
    return {
        'cetus': await fetch_cycle_data('cetus'),
        'vallis': await fetch_cycle_data('vallis'),
        'cambion': await fetch_cycle_data('cambion'),
    }


async def get_baro_status() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get current Baro Ki'Teer status.
    Returns (is_active, baro_data)
    """
    data = await fetch_baro_data()
    if not data:
        return (False, None)
    
    # Check if Baro is active
    activation = data.get("activation", "")
    expiry = data.get("expiry", "")
    
    # If we don't have both activation and expiry, Baro is not active
    if not activation or not expiry:
        return (False, data)
    
    try:
        # Parse ISO format timestamps
        activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not activation_time or not expiry_time:
            return (False, data)
        
        now = datetime.now(timezone.utc)
        
        # Baro is active only if:
        # 1. Current time is after activation
        # 2. Current time is before expiry
        # 3. Activation is before expiry (to avoid weird API responses)
        is_active = activation_time <= now < expiry_time and activation_time < expiry_time
        
        return (is_active, data)
    except Exception as e:
        logger.error(f"Error parsing Baro timestamps: {e}")
        return (False, data)


async def fetch_invasions() -> Optional[list]:
    """Fetch invasion data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/invasions", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Filter out completed invasions
                    active_invasions = [inv for inv in data if inv.get("completed", False) == False]
                    return active_invasions
                else:
                    logger.warning(f"Warframe API returned status {response.status} for invasions")
                    return None
    except Exception as e:
        logger.error(f"Error fetching invasion data: {e}")
        return None


async def fetch_archon_hunt_data() -> Optional[Dict[str, Any]]:
    """Fetch Archon Hunt data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/archonHunt", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status} for archon hunt")
                    return None
    except Exception as e:
        logger.error(f"Error fetching archon hunt data: {e}")
        return None


async def fetch_events_data() -> Optional[List[Dict[str, Any]]]:
    """Fetch active events data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/events", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Filter for active events only
                    active_events = [event for event in data if event.get("expired", False) == False]
                    return active_events
                else:
                    logger.warning(f"Warframe API returned status {response.status} for events")
                    return None
    except Exception as e:
        logger.error(f"Error fetching events data: {e}")
        return None


async def search_warframe_market_item(item_name: str, platform: str = "pc") -> Optional[Dict[str, Any]]:
    """
    Search for an item on Warframe Market and get its URL name.
    
    Args:
        item_name: The item name to search for
        platform: Platform (pc, xbox, ps4, switch)
    
    Returns:
        Item data with url_name, or None if not found
    """
    try:
        # Normalize item name for search
        search_name = item_name.lower().strip().replace(" ", "_")
        
        async with aiohttp.ClientSession() as session:
            # Search for items
            async with session.get(
                f"https://api.warframe.market/v1/items/{search_name}",
                headers={"Language": "en"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("payload", {}).get("item"):
                        return data["payload"]["item"]
                elif response.status == 404:
                    # Try fuzzy search
                    async with session.get(
                        f"https://api.warframe.market/v1/items",
                        headers={"Language": "en"},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as search_response:
                        if search_response.status == 200:
                            search_data = await search_response.json()
                            items = search_data.get("payload", {}).get("items", [])
                            # Find closest match
                            item_lower = item_name.lower()
                            for item in items:
                                if item_lower in item.get("item_name", "").lower() or item.get("url_name", "").lower() in item_lower:
                                    return item
                return None
    except Exception as e:
        logger.error(f"Error searching Warframe Market for {item_name}: {e}")
        return None


async def get_warframe_market_price(item_url_name: str, platform: str = "pc") -> Optional[Dict[str, Any]]:
    """
    Get price statistics for an item from Warframe Market.
    
    Args:
        item_url_name: The item's URL name (from search_warframe_market_item)
        platform: Platform (pc, xbox, ps4, switch)
    
    Returns:
        Price statistics dict with orders and stats, or None if error
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Get orders
            async with session.get(
                f"https://api.warframe.market/v1/items/{item_url_name}/orders",
                params={"platform": platform, "status": "ingame"},
                headers={"Language": "en"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    orders = data.get("payload", {}).get("orders", [])
                    
                    # Get statistics
                    async with session.get(
                        f"https://api.warframe.market/v1/items/{item_url_name}/statistics",
                        params={"platform": platform},
                        headers={"Language": "en"},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as stats_response:
                        stats_data = None
                        if stats_response.status == 200:
                            stats_data = await stats_response.json()
                        
                        # Calculate price stats from orders
                        sell_orders = [o for o in orders if o.get("order_type") == "sell" and o.get("user", {}).get("status") == "ingame"]
                        buy_orders = [o for o in orders if o.get("order_type") == "buy" and o.get("user", {}).get("status") == "ingame"]
                        
                        sell_prices = sorted([o.get("platinum", 0) for o in sell_orders if o.get("platinum")])
                        buy_prices = sorted([o.get("platinum", 0) for o in buy_orders if o.get("platinum")], reverse=True)
                        
                        result = {
                            "item_url_name": item_url_name,
                            "platform": platform,
                            "sell_orders": sell_orders[:5],  # Top 5 cheapest
                            "buy_orders": buy_orders[:5],  # Top 5 highest buy offers
                            "lowest_sell": sell_prices[0] if sell_prices else None,
                            "highest_buy": buy_prices[0] if buy_prices else None,
                            "stats": stats_data.get("payload", {}).get("statistics_closed", {}).get("90days", [])[-1] if stats_data else None,
                        }
                        
                        return result
                else:
                    logger.warning(f"Warframe Market API returned status {response.status} for {item_url_name}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching Warframe Market price for {item_url_name}: {e}")
        return None
