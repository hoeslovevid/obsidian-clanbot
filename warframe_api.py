"""
Warframe API functions for fetching game data.
This module handles all Warframe World State API calls.
"""
import logging
from typing import Optional, Dict, Any, Tuple
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
    
    if not activation or not expiry:
        return (False, data)
    
    try:
        # Parse ISO format timestamps
        activation_time = dateparser.parse(activation, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        expiry_time = dateparser.parse(expiry, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': True})
        
        if not activation_time or not expiry_time:
            return (False, data)
        
        now = datetime.now(timezone.utc)
        is_active = activation_time <= now <= expiry_time
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
