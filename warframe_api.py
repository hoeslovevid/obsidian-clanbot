"""
Warframe API functions for fetching game data.
This module handles all Warframe World State API calls.
"""
import logging
from typing import Optional, Dict, Any, Tuple, List
import aiohttp  # type: ignore
import dateparser  # type: ignore
from datetime import datetime, timezone, timedelta

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


async def fetch_duviri_circuit() -> Optional[Dict[str, Any]]:
    """Fetch Duviri Circuit data from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/duviriCycle", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Warframe API returned status {response.status} for duviri circuit")
                    return None
    except Exception as e:
        logger.error(f"Error fetching Duviri Circuit data: {e}")
        return None


async def fetch_alerts() -> Optional[List[Dict[str, Any]]]:
    """Fetch active alerts from Warframe World State API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.warframestat.us/pc/alerts", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    # Filter for active alerts only
                    active_alerts = [alert for alert in data if alert.get("expired", False) == False]
                    return active_alerts
                else:
                    logger.warning(f"Warframe API returned status {response.status} for alerts")
                    return None
    except Exception as e:
        logger.error(f"Error fetching alerts data: {e}")
        return None


async def fetch_twitch_stream_status(channel_name: str = "playwarframe") -> Optional[Dict[str, Any]]:
    """
    Check if a Twitch channel is live using Twitch API.
    This checks if Warframe's official channel is streaming.
    
    Args:
        channel_name: Twitch channel name (default: "playwarframe")
    
    Returns:
        Stream data dict if live, None if offline or error
    """
    try:
        # Get app access token (no user auth needed for public stream status)
        async with aiohttp.ClientSession() as session:
            # First get an app access token
            # Note: For production, you'd want to cache this token and refresh it
            # For now, we'll use a simpler approach - checking via unofficial API or scraping
            # Actually, let's use the public Helix API endpoint that doesn't require auth for basic checks
            # But we still need client-id - let's make it optional via env var
            import os
            twitch_client_id = os.getenv("TWITCH_CLIENT_ID", "")
            
            if not twitch_client_id:
                # Fallback: Try to check via alternative method or return None
                # For now, we'll skip Twitch API and use pattern-based detection instead
                return None
            
            # Get app access token
            token_url = "https://id.twitch.tv/oauth2/token"
            async with session.post(token_url, params={
                "client_id": twitch_client_id,
                "client_secret": os.getenv("TWITCH_CLIENT_SECRET", ""),
                "grant_type": "client_credentials"
            }) as token_resp:
                if token_resp.status != 200:
                    return None
                token_data = await token_resp.json()
                access_token = token_data.get("access_token")
            
            if not access_token:
                return None
            
            # Get stream status
            url = f"https://api.twitch.tv/helix/streams?user_login={channel_name}"
            headers = {
                "Client-ID": twitch_client_id,
                "Authorization": f"Bearer {access_token}"
            }
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    streams = data.get("data", [])
                    if streams and len(streams) > 0:
                        return streams[0]  # Return first stream
                    return None
                else:
                    logger.warning(f"Twitch API returned status {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching Twitch stream status: {e}")
        return None


async def calculate_next_devstream_date() -> Optional[datetime]:
    """
    Calculate the next likely devstream date.
    Warframe devstreams are typically every other Friday at 2pm ET/EDT.
    This is a fallback if Twitch API is not available.
    """
    try:
        now = datetime.now(timezone.utc)
        
        # Convert to ET/EDT (rough approximation - this is UTC-5/UTC-4)
        # For simplicity, we'll use UTC-5 (EST) and calculate next Friday
        # Devstreams are typically at 2pm ET = 7pm UTC (EST) or 6pm UTC (EDT)
        # But we'll just use the pattern: every other Friday
        
        # Find next Friday
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0:
            # Today is Friday, check if it's past 2pm ET (7pm UTC)
            et_hour = (now.hour - 5) % 24  # Rough EST conversion
            if et_hour < 14:  # Before 2pm ET
                next_friday = now
            else:
                next_friday = now + timedelta(days=14)  # Next devstream cycle (2 weeks)
        else:
            next_friday = now + timedelta(days=days_until_friday)
        
        # Check if this is a devstream week (every other week)
        # Simple heuristic: if week number is even, it's a devstream week
        week_number = next_friday.isocalendar()[1]
        if week_number % 2 == 0:
            # This is a devstream week
            # Set time to 2pm ET (7pm UTC EST, 6pm UTC EDT)
            # For simplicity, use 7pm UTC
            next_devstream = next_friday.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            # Next week is devstream week (add 1 week)
            next_devstream = (next_friday + timedelta(days=7)).replace(hour=19, minute=0, second=0, microsecond=0)
        
        return next_devstream
    except Exception as e:
        logger.error(f"Error calculating next devstream date: {e}")
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
