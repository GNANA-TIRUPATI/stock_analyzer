"""
Abstract data provider interface.

All data providers must implement this interface.
This abstraction allows swapping between yfinance, openchart,
or any future provider without changing the analysis engine.
"""

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class DataProviderError(Exception):
    """Base exception for data provider errors."""
    pass


class DataProviderAuthError(DataProviderError):
    """Authentication failure with the data provider."""
    pass


class DataProviderTimeoutError(DataProviderError):
    """Timeout when contacting the data provider."""
    pass


class DataProviderRateLimitError(DataProviderError):
    """Rate limit exceeded on the data provider."""
    pass


class BaseDataProvider(ABC):
    """
    Abstract base class for all market data providers.

    Subclasses must implement fetch_ohlcv() and get_provider_name().
    The interface returns pandas DataFrames with standardized columns.

    Expected DataFrame columns:
        - Date (datetime index or column): Trading date
        - Open (float): Opening price
        - High (float): Highest price
        - Low (float): Lowest price
        - Close (float): Closing price
        - Volume (int): Trading volume

    All prices are in INR. Timestamps are in IST.
    """

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a single stock.

        Args:
            symbol: NSE stock symbol (e.g., "RELIANCE")
            start_date: Start date for historical data
            end_date: End date for historical data
            interval: Data interval ("1d" for daily)

        Returns:
            DataFrame with OHLCV columns, or None if data unavailable.

        Raises:
            DataProviderError: On unrecoverable provider errors
            DataProviderTimeoutError: On timeout
            DataProviderRateLimitError: On rate limit
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the human-readable name of this data provider."""
        pass

    @abstractmethod
    def get_provider_info(self) -> Dict[str, str]:
        """
        Return metadata about this provider.

        Returns dict with keys:
            - name: Provider name
            - type: "official" or "unofficial"
            - url: Provider website
            - limitations: Known limitations
            - license: License/terms information
        """
        pass

    def health_check(self) -> bool:
        """
        Check if the data provider is accessible.

        Default implementation tries to fetch a known symbol.
        Override for provider-specific health checks.
        """
        try:
            from datetime import timedelta
            test_end = date.today()
            test_start = test_end - timedelta(days=7)
            result = self.fetch_ohlcv("RELIANCE", test_start, test_end)
            return result is not None and len(result) > 0
        except Exception as e:
            logger.error(f"Health check failed for {self.get_provider_name()}: {e}")
            return False
