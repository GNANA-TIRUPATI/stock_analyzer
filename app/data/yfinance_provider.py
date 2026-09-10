"""
yfinance data provider implementation.

Fetches daily OHLCV data from Yahoo Finance for NSE-listed stocks.
Uses the .NS suffix convention for NSE tickers.

IMPORTANT: yfinance is an UNOFFICIAL wrapper around Yahoo Finance.
It is the industry-standard free approach for Python-based Indian
market analysis, but it is not an officially sanctioned API.
Data should be validated before use in analysis.

Limitations:
    - Unofficial; Yahoo may change API without notice
    - Intraday data limited (1m: 7 days, <1d: 60 days)
    - May be rate-limited or IP-blocked with aggressive requests
    - Not guaranteed for commercial redistribution
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from app.data.provider import (
    BaseDataProvider,
    DataProviderError,
    DataProviderRateLimitError,
    DataProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class YFinanceProvider(BaseDataProvider):
    """
    Yahoo Finance data provider via yfinance library.

    Converts NSE symbols to Yahoo Finance format (SYMBOL.NS).
    Supports both single-stock and batch downloading with concurrency and caching.
    """

    # Class-level cache: (symbol, start_date, end_date) -> DataFrame
    _cache: Dict[Tuple[str, date, date], Optional[pd.DataFrame]] = {}

    def __init__(
        self,
        max_requests_per_second: float = 2.0,
        request_timeout: int = 30,
        max_retries: int = 2,
    ):
        """
        Initialize yfinance provider.

        Args:
            max_requests_per_second: Maximum API requests per second
            request_timeout: Timeout per request in seconds
            max_retries: Number of retries on transient failures
        """
        self._max_rps = max_requests_per_second
        self._timeout = request_timeout
        self._max_retries = max_retries
        self._last_request_time = 0.0
        self._request_count = 0

    def _throttle(self):
        """Enforce rate limiting between requests."""
        min_interval = 1.0 / self._max_rps
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _to_yahoo_symbol(self, nse_symbol: str) -> str:
        """
        Convert NSE symbol to Yahoo Finance format.

        Examples:
            RELIANCE -> RELIANCE.NS
            TCS -> TCS.NS
            M&M -> M&M.NS
        """
        if not nse_symbol.endswith(".NS"):
            return f"{nse_symbol}.NS"
        return nse_symbol

    def _from_yahoo_symbol(self, yahoo_symbol: str) -> str:
        """Convert Yahoo Finance symbol back to NSE symbol."""
        if yahoo_symbol.endswith(".NS"):
            return yahoo_symbol[:-3]
        return yahoo_symbol

    def fetch_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: str = "1d",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV data for an NSE stock from Yahoo Finance.

        Args:
            symbol: NSE symbol (e.g., "RELIANCE")
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            interval: Data interval (default "1d")

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
            Index is DatetimeIndex. Returns None if no data available.
        """
        yahoo_symbol = self._to_yahoo_symbol(symbol)

        for attempt in range(self._max_retries + 1):
            try:
                self._throttle()
                self._request_count += 1

                logger.info(
                    f"Fetching {yahoo_symbol} data from {start_date} to {end_date} "
                    f"(attempt {attempt + 1}/{self._max_retries + 1})"
                )

                ticker = yf.Ticker(yahoo_symbol)

                # yfinance end_date is exclusive, so add 1 day
                end_plus_one = end_date + timedelta(days=1)

                df = ticker.history(
                    start=start_date.isoformat(),
                    end=end_plus_one.isoformat(),
                    interval=interval,
                    auto_adjust=False,  # Get unadjusted prices for consistency
                    actions=False,  # Exclude dividends/splits from columns
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned for {yahoo_symbol}")
                    return None

                # Standardize column names
                df = self._standardize_dataframe(df, symbol)

                logger.info(
                    f"Retrieved {len(df)} records for {symbol} "
                    f"({df.index.min().date()} to {df.index.max().date()})"
                )

                return df

            except Exception as e:
                error_msg = str(e).lower()

                # Check for rate limiting
                if "429" in error_msg or "too many requests" in error_msg:
                    if attempt < self._max_retries:
                        wait_time = (2 ** attempt) * 2  # Exponential backoff
                        logger.warning(
                            f"Rate limited on {symbol}. "
                            f"Waiting {wait_time}s before retry."
                        )
                        time.sleep(wait_time)
                        continue
                    raise DataProviderRateLimitError(
                        f"Rate limited after {self._max_retries + 1} attempts: {symbol}"
                    )

                # Check for timeout
                if "timeout" in error_msg:
                    if attempt < self._max_retries:
                        logger.warning(
                            f"Timeout on {symbol}. Retrying..."
                        )
                        time.sleep(1)
                        continue
                    raise DataProviderTimeoutError(
                        f"Timeout after {self._max_retries + 1} attempts: {symbol}"
                    )

                # Other errors
                if attempt < self._max_retries:
                    logger.warning(
                        f"Error fetching {symbol}: {e}. Retrying..."
                    )
                    time.sleep(1)
                    continue

                logger.error(f"Failed to fetch {symbol} after all retries: {e}")
                return None

        return None

    def batch_fetch_ohlcv(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
        progress_callback=None,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Batch-fetch OHLCV data for multiple stocks using chunked yf.download()
        with parallel threads and in-memory caching.

        Provides live incremental progress updates as each chunk completes.

        Args:
            symbols: List of NSE symbols
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            progress_callback: Optional callback(current, total, symbol)

        Returns:
            Dict mapping NSE symbol -> standardized DataFrame (or None)
        """
        if not symbols:
            return {}

        results: Dict[str, Optional[pd.DataFrame]] = {}
        needed_symbols: List[str] = []

        # 1. Check in-memory cache first
        for s in symbols:
            cache_key = (s, start_date, end_date)
            if cache_key in self._cache:
                df = self._cache[cache_key]
                results[s] = df.copy() if df is not None else None
            else:
                needed_symbols.append(s)

        cached_count = len(symbols) - len(needed_symbols)
        if not needed_symbols:
            logger.info(f"All {len(symbols)} stocks retrieved from memory cache")
            if progress_callback:
                progress_callback(len(symbols), len(symbols), "Loaded from cache")
            return results

        if cached_count > 0:
            logger.info(f"{cached_count}/{len(symbols)} stocks retrieved from cache")
            if progress_callback:
                progress_callback(cached_count, len(symbols), "Loaded cached stocks...")
        else:
            if progress_callback:
                progress_callback(0, len(symbols), "Starting fast market download...")

        # 2. Chunk remaining symbols (25 per chunk)
        chunk_size = 25
        chunks = [
            needed_symbols[i:i + chunk_size]
            for i in range(0, len(needed_symbols), chunk_size)
        ]

        end_plus_one = end_date + timedelta(days=1)
        completed_count = cached_count
        lock = threading.Lock()

        logger.info(
            f"Downloading {len(needed_symbols)} stocks across {len(chunks)} chunks "
            f"from {start_date} to {end_date}"
        )

        def fetch_chunk(chunk_symbols: List[str]):
            nonlocal completed_count
            chunk_yahoo = [self._to_yahoo_symbol(s) for s in chunk_symbols]
            yahoo_to_nse = {self._to_yahoo_symbol(s): s for s in chunk_symbols}

            try:
                with lock:
                    self._request_count += 1

                raw = yf.download(
                    tickers=chunk_yahoo,
                    start=start_date.isoformat(),
                    end=end_plus_one.isoformat(),
                    interval="1d",
                    auto_adjust=False,
                    actions=False,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
            except Exception as e:
                logger.error(f"Chunk download failed for {chunk_symbols[:3]}...: {e}")
                raw = pd.DataFrame()

            # Parse results for this chunk
            chunk_results: Dict[str, Optional[pd.DataFrame]] = {}
            for y_sym in chunk_yahoo:
                n_sym = yahoo_to_nse[y_sym]
                try:
                    if len(chunk_yahoo) == 1:
                        t_df = raw.copy()
                    else:
                        if y_sym not in raw.columns.get_level_values(0):
                            chunk_results[n_sym] = None
                            continue
                        t_df = raw[y_sym].copy()

                    t_df = t_df.dropna(how="all")
                    if t_df.empty:
                        chunk_results[n_sym] = None
                        continue

                    t_df = self._standardize_dataframe(t_df, n_sym)
                    chunk_results[n_sym] = t_df

                except Exception as e:
                    logger.warning(f"Error parsing batch data for {n_sym}: {e}")
                    chunk_results[n_sym] = None

            # Update shared results and trigger live progress
            with lock:
                for n_sym, t_df in chunk_results.items():
                    results[n_sym] = t_df
                    self._cache[(n_sym, start_date, end_date)] = t_df
                completed_count += len(chunk_symbols)
                if progress_callback:
                    last_sym = chunk_symbols[-1] if chunk_symbols else ""
                    progress_callback(min(completed_count, len(symbols)), len(symbols), last_sym)

        # Download with up to 3 concurrent workers
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(fetch_chunk, chunks))

        logger.info(
            f"Batch download complete: {sum(1 for v in results.values() if v is not None)}"
            f"/{len(symbols)} stocks retrieved"
        )
        return results

    def _standardize_dataframe(
        self, df: pd.DataFrame, symbol: str
    ) -> pd.DataFrame:
        """
        Standardize yfinance DataFrame to our expected format.

        Ensures consistent column names, proper types, and IST timezone.
        """
        # Select only the columns we need
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        available_cols = [c for c in required_cols if c in df.columns]

        if len(available_cols) < len(required_cols):
            missing = set(required_cols) - set(available_cols)
            logger.warning(
                f"Missing columns for {symbol}: {missing}"
            )

        df = df[available_cols].copy()

        # Ensure index is DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Localize/convert to IST
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_localize("Asia/Kolkata")

        # Ensure Volume is integer
        if "Volume" in df.columns:
            df["Volume"] = df["Volume"].fillna(0).astype(int)

        # Sort by date
        df = df.sort_index()

        # Remove any exact duplicate indices
        df = df[~df.index.duplicated(keep="first")]

        return df

    def get_provider_name(self) -> str:
        return "Yahoo Finance (yfinance)"

    def get_provider_info(self) -> Dict[str, str]:
        return {
            "name": "Yahoo Finance (yfinance)",
            "type": "unofficial",
            "url": "https://github.com/ranaroussi/yfinance",
            "limitations": (
                "Unofficial wrapper around Yahoo Finance. "
                "Intraday limited to 60 days for sub-daily intervals. "
                "Daily data has no practical time limit. "
                "May be rate-limited with aggressive requests. "
                "Not guaranteed for commercial redistribution."
            ),
            "license": "Apache 2.0 (library); Yahoo Finance Terms of Service (data)",
            "reliability": "High for daily EOD data; moderate for intraday",
        }

    @property
    def request_count(self) -> int:
        """Total number of API requests made."""
        return self._request_count

