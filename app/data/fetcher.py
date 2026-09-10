"""
Data fetcher — orchestrates data retrieval for all stocks in the universe.

This module coordinates:
    1. Getting the stock universe list
    2. Fetching OHLCV data for each stock from the configured provider
    3. Validating each stock's data
    4. Returning cleaned data + exclusion records

It handles rate limiting, progress reporting, and error aggregation.
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.config.settings import AppSettings, get_scoring_weights, get_settings
from app.data.provider import (
    BaseDataProvider,
    DataProviderError,
    DataProviderRateLimitError,
    DataProviderTimeoutError,
)
from app.data.universe import get_stock_universe
from app.data.validator import DataValidator
from app.data.yfinance_provider import YFinanceProvider
from app.models.stock_data import (
    AnalysisPeriod,
    DataProvider,
    ExcludedStock,
    StockUniverse,
    ValidationWarning,
)

logger = logging.getLogger(__name__)


class DataFetchResult:
    """Container for the results of a data fetch operation."""

    def __init__(self):
        self.stock_data: Dict[str, pd.DataFrame] = {}
        self.excluded_stocks: List[ExcludedStock] = []
        self.warnings: List[ValidationWarning] = []
        self.fetch_timestamp: datetime = datetime.now()
        self.provider_name: str = ""
        self.total_universe_size: int = 0
        self.fetch_errors: int = 0
        self.last_market_data_date: Optional[date] = None

    @property
    def total_valid(self) -> int:
        return len(self.stock_data)

    @property
    def total_excluded(self) -> int:
        return len(self.excluded_stocks)


def create_provider(settings: Optional[AppSettings] = None) -> BaseDataProvider:
    """
    Create the appropriate data provider based on configuration.

    Args:
        settings: Application settings. If None, loads from environment.

    Returns:
        Configured data provider instance.
    """
    if settings is None:
        settings = get_settings()

    provider_name = settings.data_provider.lower()

    if provider_name == "yfinance":
        return YFinanceProvider(
            max_requests_per_second=settings.max_requests_per_second,
            request_timeout=settings.request_timeout,
        )
    else:
        # Default to yfinance
        logger.warning(
            f"Unknown provider '{provider_name}', defaulting to yfinance"
        )
        return YFinanceProvider(
            max_requests_per_second=settings.max_requests_per_second,
            request_timeout=settings.request_timeout,
        )


def calculate_date_range(
    analysis_period: int,
    reference_date: Optional[date] = None,
) -> Tuple[date, date]:
    """
    Calculate the start and end dates for data retrieval.

    We request extra calendar days to account for weekends and holidays,
    ensuring we get enough actual trading sessions.

    Args:
        analysis_period: Number of trading days needed (15 or 30)
        reference_date: End date (default: today)

    Returns:
        Tuple of (start_date, end_date)
    """
    if reference_date is None:
        reference_date = date.today()

    end_date = reference_date

    # Request ~50% more calendar days than trading days to account
    # for weekends (~2/7 days) and holidays
    calendar_days_needed = int(analysis_period * 1.6) + 10  # Extra buffer
    start_date = end_date - timedelta(days=calendar_days_needed)

    return start_date, end_date


def fetch_all_stocks(
    analysis_period: int = 30,
    universe: StockUniverse = StockUniverse.NIFTY_200,
    provider: Optional[BaseDataProvider] = None,
    settings: Optional[AppSettings] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> DataFetchResult:
    """
    Fetch and validate OHLCV data for all stocks in the universe.

    Uses batch download (yf.download) when provider supports it for
    dramatically faster data retrieval. Falls back to sequential
    fetching for providers without batch support.

    Args:
        analysis_period: Number of trading days to analyze (15 or 30)
        universe: Stock universe to analyze
        provider: Data provider (created from config if None)
        settings: App settings (loaded from env if None)
        progress_callback: Optional callback(current, total, symbol)
            for progress reporting

    Returns:
        DataFetchResult containing cleaned data, exclusions, and warnings
    """
    if settings is None:
        settings = get_settings()

    if provider is None:
        provider = create_provider(settings)

    result = DataFetchResult()
    result.provider_name = provider.get_provider_name()
    result.fetch_timestamp = datetime.now()

    # Step 1: Get stock universe
    logger.info(f"Fetching stock universe: {universe.value}")
    try:
        symbols = get_stock_universe(universe)
    except Exception as e:
        logger.error(f"Failed to get stock universe: {e}")
        raise DataProviderError(f"Unable to determine stock universe: {e}")

    result.total_universe_size = len(symbols)
    logger.info(f"Universe contains {len(symbols)} stocks")

    # Step 2: Calculate date range
    start_date, end_date = calculate_date_range(analysis_period)
    logger.info(
        f"Date range: {start_date} to {end_date} "
        f"(targeting {analysis_period} trading days)"
    )

    # Step 3: Initialize validator
    scoring_weights = get_scoring_weights()
    validator = DataValidator(scoring_weights)

    # Step 4: Try batch fetch if provider supports it (much faster)
    use_batch = hasattr(provider, 'batch_fetch_ohlcv')

    if use_batch:
        logger.info("Using batch download mode for faster data retrieval")
        raw_data = _batch_fetch(
            provider, symbols, start_date, end_date, progress_callback
        )
    else:
        logger.info("Using sequential download mode")
        raw_data = _sequential_fetch(
            provider, symbols, start_date, end_date, result, progress_callback
        )

    # Step 5: Validate each stock's data
    if progress_callback:
        progress_callback(0, len(symbols), "Validating data...")

    for i, symbol in enumerate(symbols):
        if progress_callback:
            progress_callback(i + 1, len(symbols), symbol)

        # Check if we have data for this symbol
        if use_batch:
            df = raw_data.get(symbol)
            if df is None:
                result.excluded_stocks.append(ExcludedStock(
                    symbol=symbol,
                    reason="No data returned by provider",
                    details=f"Provider: {provider.get_provider_name()}",
                ))
                result.fetch_errors += 1
                continue
        else:
            # Sequential mode already populated result.excluded_stocks
            df = raw_data.get(symbol)
            if df is None:
                continue  # Already handled in _sequential_fetch

        try:
            # Validate data
            cleaned_df, warnings, exclusion = validator.validate_stock(
                symbol=symbol,
                df=df,
                expected_trading_days=analysis_period,
            )

            result.warnings.extend(warnings)

            if exclusion:
                result.excluded_stocks.append(exclusion)
                logger.info(
                    f"Excluded {symbol}: {exclusion.reason}"
                )
                continue

            if cleaned_df is not None and not cleaned_df.empty:
                # Trim to the requested number of trading days
                if len(cleaned_df) > analysis_period:
                    cleaned_df = cleaned_df.tail(analysis_period)

                result.stock_data[symbol] = cleaned_df

                # Track latest data date
                last_date = cleaned_df.index.max()
                if hasattr(last_date, 'date'):
                    last_date = last_date.date()
                if (
                    result.last_market_data_date is None
                    or last_date > result.last_market_data_date
                ):
                    result.last_market_data_date = last_date

        except Exception as e:
            logger.error(f"Validation error for {symbol}: {e}")
            result.excluded_stocks.append(ExcludedStock(
                symbol=symbol,
                reason="Validation error",
                details=str(e),
            ))
            result.fetch_errors += 1

    # Summary logging
    logger.info(
        f"Data fetch complete: "
        f"{result.total_valid} valid / "
        f"{result.total_excluded} excluded / "
        f"{result.total_universe_size} total"
    )

    if result.total_valid == 0:
        logger.error("No valid stock data retrieved. Analysis cannot proceed.")

    return result


def _batch_fetch(
    provider,
    symbols: List[str],
    start_date,
    end_date,
    progress_callback,
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Batch-fetch all stocks in one yf.download() call.
    Returns dict of symbol -> DataFrame (or None).
    """
    if progress_callback:
        progress_callback(0, len(symbols), "Downloading all stocks (batch)...")

    try:
        raw_data = provider.batch_fetch_ohlcv(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            progress_callback=progress_callback,
        )
    except Exception as e:
        logger.error(f"Batch fetch failed: {e}. Returning empty.")
        raw_data = {}

    return raw_data


def _sequential_fetch(
    provider,
    symbols: List[str],
    start_date,
    end_date,
    result: DataFetchResult,
    progress_callback,
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    Fetch stocks one-by-one (fallback for providers without batch support).
    Returns dict of symbol -> DataFrame. Populates result.excluded_stocks
    for failures.
    """
    raw_data: Dict[str, Optional[pd.DataFrame]] = {}

    for i, symbol in enumerate(symbols):
        if progress_callback:
            progress_callback(i + 1, len(symbols), symbol)

        logger.info(f"[{i+1}/{len(symbols)}] Processing {symbol}")

        try:
            df = provider.fetch_ohlcv(symbol, start_date, end_date)

            if df is None or df.empty:
                result.excluded_stocks.append(ExcludedStock(
                    symbol=symbol,
                    reason="No data returned by provider",
                    details=f"Provider: {provider.get_provider_name()}",
                ))
                result.fetch_errors += 1
                continue

            raw_data[symbol] = df

        except DataProviderRateLimitError:
            logger.warning(f"Rate limited while fetching {symbol}. Pausing...")
            time.sleep(10)
            result.excluded_stocks.append(ExcludedStock(
                symbol=symbol,
                reason="Rate limited by data provider",
                details="Consider reducing request rate or trying later",
            ))
            result.fetch_errors += 1

        except DataProviderTimeoutError:
            logger.warning(f"Timeout fetching {symbol}")
            result.excluded_stocks.append(ExcludedStock(
                symbol=symbol,
                reason="Data provider timeout",
                details="Request timed out after retries",
            ))
            result.fetch_errors += 1

        except Exception as e:
            logger.error(f"Unexpected error fetching {symbol}: {e}")
            result.excluded_stocks.append(ExcludedStock(
                symbol=symbol,
                reason="Fetch error",
                details=str(e),
            ))
            result.fetch_errors += 1

    return raw_data

