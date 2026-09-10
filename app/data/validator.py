"""
Data validation engine.

Validates OHLCV data quality before analysis.
Returns cleaned data along with warnings and exclusion records.

Validation checks (from requirements):
    1. Missing timestamps
    2. Duplicate records
    3. Invalid OHLC relationships (High < Low, etc.)
    4. Zero/negative prices
    5. Missing/zero volume
    6. Suspicious gaps (possible corporate actions)
    7. Incomplete trading sessions (< 80% coverage)
    8. Stale data
    9. API errors (handled upstream)

If data is invalid, the stock is excluded with a documented reason.
Values are NEVER fabricated or silently substituted.
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.config.settings import get_scoring_weights
from app.models.stock_data import ExcludedStock, ValidationWarning

logger = logging.getLogger(__name__)


class DataValidator:
    """
    Validates and cleans OHLCV data for analysis quality.

    The validator runs all checks on each stock's data and returns:
        - Cleaned DataFrame (invalid rows removed)
        - List of warnings (non-fatal issues)
        - Exclusion record if stock should be excluded entirely

    The validator NEVER fabricates or estimates missing data.
    """

    def __init__(self, scoring_weights=None):
        """
        Initialize validator with configurable thresholds.

        Args:
            scoring_weights: ScoringWeights instance (loaded from YAML).
                If None, loads default configuration.
        """
        if scoring_weights is None:
            scoring_weights = get_scoring_weights()
        self._thresholds = scoring_weights.thresholds

    def validate_stock(
        self,
        symbol: str,
        df: pd.DataFrame,
        expected_trading_days: int,
    ) -> Tuple[Optional[pd.DataFrame], List[ValidationWarning], Optional[ExcludedStock]]:
        """
        Validate a single stock's OHLCV data.

        Args:
            symbol: Stock symbol
            df: Raw OHLCV DataFrame from data provider
            expected_trading_days: Expected number of trading sessions

        Returns:
            Tuple of:
                - Cleaned DataFrame (None if stock is excluded)
                - List of validation warnings
                - ExcludedStock record (None if stock passes validation)
        """
        warnings: List[ValidationWarning] = []

        # Check 0: Null or empty data
        if df is None or df.empty:
            return None, warnings, ExcludedStock(
                symbol=symbol,
                reason="No data available",
                details="Data provider returned no records for this symbol",
            )

        cleaned = df.copy()
        original_rows = len(cleaned)

        # Check 1: Duplicate timestamps
        cleaned, dup_warnings = self._check_duplicates(symbol, cleaned)
        warnings.extend(dup_warnings)

        # Check 2: Missing required columns
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        missing_cols = [c for c in required_cols if c not in cleaned.columns]
        if missing_cols:
            return None, warnings, ExcludedStock(
                symbol=symbol,
                reason="Missing required data columns",
                details=f"Missing: {', '.join(missing_cols)}",
            )

        # Check 3: Zero/negative prices
        cleaned, price_warnings = self._check_prices(symbol, cleaned)
        warnings.extend(price_warnings)

        # Check 4: Invalid OHLC relationships
        cleaned, ohlc_warnings = self._check_ohlc_relationships(symbol, cleaned)
        warnings.extend(ohlc_warnings)

        # Check 5: Zero volume
        vol_warnings = self._check_volume(symbol, cleaned)
        warnings.extend(vol_warnings)

        # Check 6: Check if too many rows were invalidated
        max_invalid = self._thresholds["max_invalid_ohlc_fraction"]
        if original_rows > 0:
            invalid_fraction = (original_rows - len(cleaned)) / original_rows
            if invalid_fraction > max_invalid:
                return None, warnings, ExcludedStock(
                    symbol=symbol,
                    reason="Excessive invalid data",
                    details=(
                        f"{invalid_fraction:.0%} of records were invalid "
                        f"(threshold: {max_invalid:.0%})"
                    ),
                )

        # Check 7: Insufficient trading sessions
        min_coverage = self._thresholds["min_session_coverage"]
        if len(cleaned) < expected_trading_days * min_coverage:
            return None, warnings, ExcludedStock(
                symbol=symbol,
                reason="Insufficient trading sessions",
                details=(
                    f"Only {len(cleaned)} sessions available, "
                    f"need at least {int(expected_trading_days * min_coverage)} "
                    f"({min_coverage:.0%} of {expected_trading_days})"
                ),
            )

        # Check 8: Zero volume check (exclusion)
        max_zero_vol = self._thresholds["max_zero_volume_fraction"]
        if "Volume" in cleaned.columns:
            zero_vol_frac = (cleaned["Volume"] == 0).sum() / len(cleaned)
            if zero_vol_frac > max_zero_vol:
                return None, warnings, ExcludedStock(
                    symbol=symbol,
                    reason="Excessive zero-volume days",
                    details=(
                        f"{zero_vol_frac:.0%} of days had zero volume "
                        f"(threshold: {max_zero_vol:.0%})"
                    ),
                )

        # Check 9: Suspicious gaps (possible corporate actions)
        gap_warnings = self._check_suspicious_gaps(symbol, cleaned)
        warnings.extend(gap_warnings)

        # Check 10: Stale data
        stale_warnings = self._check_stale_data(symbol, cleaned)
        warnings.extend(stale_warnings)

        logger.info(
            f"Validation for {symbol}: {len(cleaned)}/{original_rows} records valid, "
            f"{len(warnings)} warnings"
        )

        return cleaned, warnings, None

    def _check_duplicates(
        self, symbol: str, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, List[ValidationWarning]]:
        """Remove duplicate timestamps, keeping the first occurrence."""
        warnings = []
        duplicated = df.index.duplicated(keep="first")
        dup_count = duplicated.sum()

        if dup_count > 0:
            warnings.append(ValidationWarning(
                symbol=symbol,
                warning_type="DUPLICATE_TIMESTAMPS",
                message=f"Removed {dup_count} duplicate timestamp(s)",
                severity="WARNING",
            ))
            df = df[~duplicated]

        return df, warnings

    def _check_prices(
        self, symbol: str, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, List[ValidationWarning]]:
        """Check for zero or negative prices and remove invalid rows."""
        warnings = []
        price_cols = ["Open", "High", "Low", "Close"]

        invalid_mask = pd.Series(False, index=df.index)

        for col in price_cols:
            if col in df.columns:
                # Check for NaN
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    warnings.append(ValidationWarning(
                        symbol=symbol,
                        warning_type="MISSING_PRICE",
                        message=f"{nan_count} missing {col} value(s)",
                        severity="WARNING",
                    ))
                    invalid_mask |= df[col].isna()

                # Check for zero or negative
                bad = df[col] <= 0
                bad_count = bad.sum()
                if bad_count > 0:
                    warnings.append(ValidationWarning(
                        symbol=symbol,
                        warning_type="INVALID_PRICE",
                        message=f"{bad_count} zero/negative {col} value(s)",
                        severity="WARNING",
                    ))
                    invalid_mask |= bad

        df = df[~invalid_mask]
        return df, warnings

    def _check_ohlc_relationships(
        self, symbol: str, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, List[ValidationWarning]]:
        """
        Validate OHLC relationships.

        Rules:
            - High must be >= Low
            - Open and Close should be within [Low, High] (warning only)
        """
        warnings = []

        if "High" in df.columns and "Low" in df.columns:
            # Critical: High < Low (remove these rows)
            invalid = df["High"] < df["Low"]
            invalid_count = invalid.sum()
            if invalid_count > 0:
                warnings.append(ValidationWarning(
                    symbol=symbol,
                    warning_type="HIGH_LESS_THAN_LOW",
                    message=f"{invalid_count} day(s) where High < Low (removed)",
                    severity="ERROR",
                ))
                df = df[~invalid]

        # Warning only: Open/Close outside [Low, High]
        if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
            oob_open = (df["Open"] < df["Low"]) | (df["Open"] > df["High"])
            oob_close = (df["Close"] < df["Low"]) | (df["Close"] > df["High"])

            if oob_open.sum() > 0:
                warnings.append(ValidationWarning(
                    symbol=symbol,
                    warning_type="OPEN_OUT_OF_RANGE",
                    message=(
                        f"{oob_open.sum()} day(s) where Open is outside [Low, High]"
                    ),
                    severity="WARNING",
                ))

            if oob_close.sum() > 0:
                warnings.append(ValidationWarning(
                    symbol=symbol,
                    warning_type="CLOSE_OUT_OF_RANGE",
                    message=(
                        f"{oob_close.sum()} day(s) where Close is outside [Low, High]"
                    ),
                    severity="WARNING",
                ))

        return df, warnings

    def _check_volume(
        self, symbol: str, df: pd.DataFrame
    ) -> List[ValidationWarning]:
        """Check for zero volume days (warning, not removal)."""
        warnings = []

        if "Volume" in df.columns:
            zero_vol = (df["Volume"] == 0).sum()
            if zero_vol > 0:
                warnings.append(ValidationWarning(
                    symbol=symbol,
                    warning_type="ZERO_VOLUME",
                    message=f"{zero_vol} day(s) with zero volume",
                    severity="WARNING",
                ))

        return warnings

    def _check_suspicious_gaps(
        self, symbol: str, df: pd.DataFrame
    ) -> List[ValidationWarning]:
        """
        Check for suspiciously large overnight gaps.

        Large gaps (>20%) may indicate corporate actions like stock splits,
        bonus issues, or other events that affect price continuity.
        """
        warnings = []
        threshold = self._thresholds["suspicious_gap_threshold_pct"] / 100

        if len(df) < 2 or "Close" not in df.columns or "Open" not in df.columns:
            return warnings

        prev_close = df["Close"].shift(1)
        gap_pct = ((df["Open"] - prev_close) / prev_close).abs()

        # Skip first row (no previous close)
        gap_pct = gap_pct.iloc[1:]
        large_gaps = gap_pct[gap_pct > threshold]

        if len(large_gaps) > 0:
            for idx, gap_val in large_gaps.items():
                trading_date = idx.date() if hasattr(idx, 'date') else idx
                warnings.append(ValidationWarning(
                    symbol=symbol,
                    warning_type="SUSPICIOUS_GAP",
                    message=(
                        f"Large overnight gap of {gap_val:.1%} on {trading_date}. "
                        f"Possible corporate action."
                    ),
                    severity="WARNING",
                    trading_date=trading_date,
                ))

        return warnings

    def _check_stale_data(
        self, symbol: str, df: pd.DataFrame
    ) -> List[ValidationWarning]:
        """Check if the most recent data point is stale."""
        warnings = []
        max_stale_days = self._thresholds["stale_data_max_days"]

        if df.empty:
            return warnings

        last_date = df.index.max()
        if hasattr(last_date, 'date'):
            last_date = last_date.date()

        today = date.today()
        # Count business days between last data and today
        business_days = np.busday_count(last_date, today)

        if business_days > max_stale_days:
            warnings.append(ValidationWarning(
                symbol=symbol,
                warning_type="STALE_DATA",
                message=(
                    f"Last data point is {business_days} trading days old "
                    f"(last: {last_date}, threshold: {max_stale_days} days)"
                ),
                severity="WARNING",
            ))

        return warnings
