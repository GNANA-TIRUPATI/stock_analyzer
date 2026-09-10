"""
Stock universe management.

Defines and retrieves the eligible stock universe for analysis.
Uses the niftystocks library to programmatically fetch NIFTY index constituents.

The universe is configurable:
    - NIFTY_50: Top 50 NSE companies
    - NIFTY_100: Top 100 NSE companies
    - NIFTY_200: Top 200 NSE companies (default)
    - NIFTY_500: Top 500 NSE companies
    - CUSTOM: User-provided list

ETFs, indices, and derivatives are excluded by default.
"""

import logging
from typing import List, Optional, Set

from app.models.stock_data import StockUniverse

logger = logging.getLogger(__name__)

# Renamed / reorganized NSE symbols -> current active Yahoo Finance symbols
SYMBOL_ALIASES = {
    "MCDOWELL-N": "UNITDSPR",
    "ADANITRANS": "ADANIENSOL",
    "CADILAHC": "ZYDUSLIFE",
    "AMARAJABAT": "ARE&M",
    "MOTHERSUMI": "MOTHERSON",
    "SRTRANSFIN": "SHRIRAMFIN",
    "L&TFH": "LTF",
    "GMRINFRA": "GMRAIRPORT",
    "IBULHSGFIN": "SAMMAANCAP",
}

# Known ETFs/instruments and delisted/merged entities to exclude from equity analysis
DEFAULT_EXCLUSIONS: Set[str] = {
    # Gold ETFs
    "GOLDBEES", "GOLDCASE", "GOLDETF",
    # Nifty ETFs
    "NIFTYBEES", "NIFTYETF", "JUNIORBEES",
    # Bank ETFs
    "BANKBEES", "BANKETF",
    # Other ETFs
    "LIQUIDBEES", "SETFGOLD", "SETFNIF50", "SETFNIFBK",
    "ICICIB22", "LICNETFN50", "UTINIFTETF",
    # Index-based products
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    # Delisted or merged entities
    "MINDTREE", "HDFC", "DHANI", "ISEC", "LTI",
}


def get_stock_universe(
    universe: StockUniverse = StockUniverse.NIFTY_200,
    custom_symbols: Optional[List[str]] = None,
    additional_exclusions: Optional[Set[str]] = None,
) -> List[str]:
    """
    Get the list of stock symbols for the given universe.

    Args:
        universe: Which NIFTY index to use as the stock universe
        custom_symbols: Custom list of symbols (only used with CUSTOM universe)
        additional_exclusions: Additional symbols to exclude

    Returns:
        List of NSE stock symbols eligible for analysis

    Raises:
        ValueError: If universe is CUSTOM but no custom_symbols provided
        RuntimeError: If unable to fetch the stock list
    """
    exclusions = DEFAULT_EXCLUSIONS.copy()
    if additional_exclusions:
        exclusions.update(additional_exclusions)

    if universe == StockUniverse.CUSTOM:
        if not custom_symbols:
            raise ValueError(
                "custom_symbols must be provided when using CUSTOM universe"
            )
        symbols = [s.upper().strip() for s in custom_symbols]
        symbols = [s for s in symbols if s and s not in exclusions]
        logger.info(f"Custom universe: {len(symbols)} stocks")
        return symbols

    try:
        symbols = _fetch_nifty_stocks(universe)
    except Exception as e:
        logger.error(f"Failed to fetch {universe.value} stocks: {e}")
        logger.info("Falling back to hardcoded NIFTY 50 list")
        symbols = _get_fallback_nifty50()

    # Apply exclusions and aliases
    original_count = len(symbols)
    symbols = [s for s in symbols if s not in exclusions]
    symbols = [SYMBOL_ALIASES.get(s, s) for s in symbols]
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for s in symbols:
        if s not in seen and s not in exclusions:
            seen.add(s)
            deduped.append(s)
    symbols = deduped
    excluded_count = original_count - len(symbols)

    if excluded_count > 0:
        logger.info(
            f"Excluded {excluded_count} non-equity instruments from universe"
        )

    logger.info(
        f"Stock universe {universe.value}: {len(symbols)} eligible stocks"
    )

    return symbols


def _fetch_nifty_stocks(universe: StockUniverse) -> List[str]:
    """
    Fetch stock list from niftystocks library.

    Falls back to a hardcoded list if the library is unavailable.
    """
    try:
        from niftystocks import ns

        if universe == StockUniverse.NIFTY_50:
            return ns.get_nifty50()
        elif universe == StockUniverse.NIFTY_100:
            return ns.get_nifty100()
        elif universe == StockUniverse.NIFTY_200:
            return ns.get_nifty200()
        elif universe == StockUniverse.NIFTY_500:
            return ns.get_nifty500()
        else:
            raise ValueError(f"Unknown universe: {universe}")

    except ImportError:
        logger.warning(
            "niftystocks library not available. Using fallback NIFTY 50 list."
        )
        return _get_fallback_nifty50()
    except Exception as e:
        logger.warning(f"Error fetching from niftystocks: {e}")
        raise


def _get_fallback_nifty50() -> List[str]:
    """
    Hardcoded NIFTY 50 constituent list as fallback.

    NOTE: This list may become stale over time as NIFTY 50 is rebalanced
    semi-annually. The niftystocks library is the preferred source.
    This fallback ensures the application can run even if the library
    fails to connect.

    Last updated: 2025 (approximate)
    """
    return [
        "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
        "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
        "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
        "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
        "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
        "ITC", "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK",
        "LT", "M&M", "MARUTI", "NTPC", "NESTLEIND",
        "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
        "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
        "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    ]


def get_universe_info(universe: StockUniverse) -> dict:
    """Get metadata about the stock universe."""
    descriptions = {
        StockUniverse.NIFTY_50: "Top 50 NSE companies by market cap",
        StockUniverse.NIFTY_100: "Top 100 NSE companies by market cap",
        StockUniverse.NIFTY_200: "Top 200 NSE companies by market cap",
        StockUniverse.NIFTY_500: "Top 500 NSE companies by market cap",
        StockUniverse.CUSTOM: "User-defined stock list",
    }
    return {
        "universe": universe.value,
        "description": descriptions.get(universe, "Unknown"),
        "source": "niftystocks library (NSE index constituents)",
        "rebalancing": "Semi-annual by NSE Indices Limited",
    }
