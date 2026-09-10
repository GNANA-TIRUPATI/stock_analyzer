"""
Metrics calculation module.

Computes all day-trading analysis metrics from validated OHLCV data.
Each metric has a documented formula and is independently testable.

METRIC CATEGORIES:
    A. Intraday Price Movement — measures daily price swing characteristics
    B. Volatility — measures price variability
    C. Volume / Liquidity — measures trading activity
    D. Consistency — measures regularity of movement
    E. Risk — measures adverse movement characteristics

ALL FORMULAS ARE DOCUMENTED IN DOCSTRINGS.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from app.models.stock_data import StockMetrics

logger = logging.getLogger(__name__)


def calculate_metrics(symbol: str, df: pd.DataFrame) -> Optional[StockMetrics]:
    """
    Calculate all day-trading analysis metrics for a single stock.

    Args:
        symbol: Stock symbol
        df: Validated OHLCV DataFrame with columns:
            Open, High, Low, Close, Volume
            DatetimeIndex sorted ascending

    Returns:
        StockMetrics if calculation succeeds, None on failure

    The DataFrame must have at least 2 rows for return-based calculations.
    """
    if df is None or len(df) < 2:
        logger.warning(
            f"Insufficient data for {symbol}: need >= 2 rows, got {len(df) if df is not None else 0}"
        )
        return None

    try:
        # A. Intraday Price Movement
        movement = _calculate_movement_metrics(df)

        # B. Volatility
        volatility = _calculate_volatility_metrics(df)

        # C. Volume / Liquidity
        liquidity = _calculate_liquidity_metrics(df)

        # D. Consistency
        consistency = _calculate_consistency_metrics(df, movement["hl_range_pct_series"])

        # E. Risk
        risk = _calculate_risk_metrics(df)

        return StockMetrics(
            symbol=symbol,
            # Movement
            avg_hl_range_pct=movement["avg_hl_range_pct"],
            avg_oc_move_pct=movement["avg_oc_move_pct"],
            median_hl_range_pct=movement["median_hl_range_pct"],
            avg_intraday_move_abs=movement["avg_intraday_move_abs"],
            # Volatility
            daily_return_std=volatility["daily_return_std"],
            atr=volatility["atr"],
            normalized_atr=volatility["normalized_atr"],
            # Liquidity
            avg_volume=liquidity["avg_volume"],
            volume_cv=liquidity["volume_cv"],
            relative_volume_trend=liquidity["relative_volume_trend"],
            # Consistency
            movement_frequency=consistency["movement_frequency"],
            max_consecutive_active_days=consistency["max_consecutive_active_days"],
            # Risk
            max_adverse_move=risk["max_adverse_move"],
            downside_deviation=risk["downside_deviation"],
            gap_risk=risk["gap_risk"],
            # Metadata
            trading_days_analyzed=len(df),
            avg_close_price=float(df["Close"].mean()),
        )

    except Exception as e:
        logger.error(f"Error calculating metrics for {symbol}: {e}", exc_info=True)
        return None


# =============================================================================
# A. INTRADAY PRICE MOVEMENT
# =============================================================================

def _calculate_movement_metrics(df: pd.DataFrame) -> dict:
    """
    Calculate intraday price movement metrics.

    Metrics:
        avg_hl_range_pct: Average of (High - Low) / Low × 100 for each day
            Measures the total price swing as a percentage of the low.

        avg_oc_move_pct: Average of |Close - Open| / Open × 100 for each day
            Measures directional movement within the session.

        median_hl_range_pct: Median of the daily HL range percentages
            More robust than mean; resistant to single extreme days.

        avg_intraday_move_abs: Average of (High - Low) in absolute INR
            Raw price movement without percentage normalization.
    """
    # High-Low range as percentage of Low
    # Formula: (High_i - Low_i) / Low_i × 100
    hl_range_pct = (df["High"] - df["Low"]) / df["Low"] * 100

    # Open-to-Close movement as percentage of Open
    # Formula: |Close_i - Open_i| / Open_i × 100
    oc_move_pct = (df["Close"] - df["Open"]).abs() / df["Open"] * 100

    # Absolute intraday movement in INR
    # Formula: High_i - Low_i
    intraday_abs = df["High"] - df["Low"]

    return {
        "avg_hl_range_pct": float(hl_range_pct.mean()),
        "avg_oc_move_pct": float(oc_move_pct.mean()),
        "median_hl_range_pct": float(hl_range_pct.median()),
        "avg_intraday_move_abs": float(intraday_abs.mean()),
        "hl_range_pct_series": hl_range_pct,  # Used by consistency calculation
    }


# =============================================================================
# B. VOLATILITY
# =============================================================================

def _calculate_volatility_metrics(df: pd.DataFrame) -> dict:
    """
    Calculate historical volatility metrics.

    Metrics:
        daily_return_std: Standard deviation of daily close-to-close returns
            Formula: std( (Close_t - Close_{t-1}) / Close_{t-1} )
            Classic volatility measure. Higher = more price variability.

        atr: Average True Range in absolute INR
            Formula: mean(TR) where
                TR_t = max(
                    High_t - Low_t,
                    |High_t - Close_{t-1}|,
                    |Low_t - Close_{t-1}|
                )
            Standard volatility metric that accounts for overnight gaps.

        normalized_atr: ATR as percentage of closing price
            Formula: ATR / mean(Close) × 100
            Allows cross-stock comparison regardless of price level.
    """
    # Daily returns (close-to-close)
    daily_returns = df["Close"].pct_change().dropna()
    daily_return_std = float(daily_returns.std())

    # True Range
    # TR = max(H-L, |H-PrevClose|, |L-PrevClose|)
    prev_close = df["Close"].shift(1)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - prev_close).abs()
    tr3 = (df["Low"] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Drop first row (no previous close)
    true_range = true_range.iloc[1:]

    atr = float(true_range.mean())
    avg_close = float(df["Close"].mean())
    normalized_atr = (atr / avg_close * 100) if avg_close > 0 else 0.0

    return {
        "daily_return_std": daily_return_std,
        "atr": atr,
        "normalized_atr": normalized_atr,
    }


# =============================================================================
# C. VOLUME / LIQUIDITY
# =============================================================================

def _calculate_liquidity_metrics(df: pd.DataFrame) -> dict:
    """
    Calculate volume and liquidity metrics.

    Metrics:
        avg_volume: Simple mean of daily volume
            Formula: mean(Volume_1, Volume_2, ..., Volume_n)

        volume_cv: Coefficient of variation of daily volume
            Formula: std(Volume) / mean(Volume)
            Lower values indicate more consistent daily volume.
            Score inversion happens at the scoring stage, not here.

        relative_volume_trend: Recent volume relative to period average
            Formula: mean(Volume of last 5 days) / mean(Volume of all days)
            Values > 1.0 indicate increasing volume trend.
    """
    # Filter out zero-volume days for meaningful statistics
    volumes = df["Volume"].copy()
    non_zero_volumes = volumes[volumes > 0]

    if len(non_zero_volumes) == 0:
        return {
            "avg_volume": 0.0,
            "volume_cv": 0.0,
            "relative_volume_trend": 0.0,
        }

    avg_volume = float(non_zero_volumes.mean())

    # Coefficient of variation
    vol_std = float(non_zero_volumes.std())
    volume_cv = vol_std / avg_volume if avg_volume > 0 else 0.0

    # Relative volume trend (last 5 days vs all)
    last_5 = volumes.tail(5)
    last_5_nonzero = last_5[last_5 > 0]
    if len(last_5_nonzero) > 0 and avg_volume > 0:
        relative_volume_trend = float(last_5_nonzero.mean() / avg_volume)
    else:
        relative_volume_trend = 1.0  # Neutral if insufficient data

    return {
        "avg_volume": avg_volume,
        "volume_cv": volume_cv,
        "relative_volume_trend": relative_volume_trend,
    }


# =============================================================================
# D. CONSISTENCY
# =============================================================================

def _calculate_consistency_metrics(
    df: pd.DataFrame,
    hl_range_pct: pd.Series,
) -> dict:
    """
    Calculate consistency of intraday movement.

    Metrics:
        movement_frequency: Fraction of days with HL range above adaptive threshold
            Formula: count(HL_range%_i > threshold) / total_days
            Threshold = median(HL_range%) × movement_threshold_multiplier
            Measures how often the stock shows meaningful movement,
            rather than relying on a single exceptional day.

        max_consecutive_active_days: Longest streak of consecutive "active" days
            An "active" day is one where HL_range% > threshold.
            Longer streaks indicate more reliable day-trading opportunity.
    """
    # Adaptive threshold: half the stock's own median range
    # This ensures each stock is judged relative to its own typical behavior
    median_range = float(hl_range_pct.median())
    threshold = median_range * 0.5  # movement_threshold_multiplier from config

    # Binary active/inactive classification
    active_days = hl_range_pct > threshold

    # Movement frequency
    movement_frequency = float(active_days.sum() / len(active_days)) if len(active_days) > 0 else 0.0

    # Maximum consecutive active days
    max_consecutive = _max_consecutive_true(active_days)

    return {
        "movement_frequency": movement_frequency,
        "max_consecutive_active_days": max_consecutive,
    }


def _max_consecutive_true(series: pd.Series) -> int:
    """
    Calculate the maximum number of consecutive True values in a boolean series.

    Uses a groupby approach to identify runs of consecutive True values.
    """
    if series.empty or not series.any():
        return 0

    # Create groups of consecutive same values
    groups = (series != series.shift()).cumsum()
    # Filter to only True groups and count their sizes
    true_groups = series.groupby(groups).sum()
    return int(true_groups.max()) if len(true_groups) > 0 else 0


# =============================================================================
# E. RISK
# =============================================================================

def _calculate_risk_metrics(df: pd.DataFrame) -> dict:
    """
    Calculate risk characteristics.

    Metrics:
        max_adverse_move: Maximum single-day absolute return
            Formula: max(|daily_return_t|)
            Captures the worst-case single-day loss potential.

        downside_deviation: Standard deviation of negative daily returns only
            Formula: std(daily_return_t where daily_return_t < 0)
            Asymmetric risk measure — penalizes downside more than upside.

        gap_risk: Fraction of days with large overnight gaps (>2%)
            Formula: count(|Open_t - Close_{t-1}| / Close_{t-1} > 0.02) / total_days
            Overnight gaps are uncontrollable risk for day traders.
    """
    daily_returns = df["Close"].pct_change().dropna()

    # Max absolute single-day return
    max_adverse_move = float(daily_returns.abs().max()) if len(daily_returns) > 0 else 0.0

    # Downside deviation (std of negative returns only)
    negative_returns = daily_returns[daily_returns < 0]
    if len(negative_returns) >= 2:
        downside_deviation = float(negative_returns.std())
    elif len(negative_returns) == 1:
        downside_deviation = float(abs(negative_returns.iloc[0]))
    else:
        downside_deviation = 0.0

    # Gap risk: fraction of days with overnight gap > 2%
    gap_threshold = 0.02  # 2%
    if len(df) >= 2:
        prev_close = df["Close"].shift(1)
        overnight_gap = ((df["Open"] - prev_close) / prev_close).abs()
        overnight_gap = overnight_gap.iloc[1:]  # Drop first row
        large_gaps = overnight_gap > gap_threshold
        gap_risk = float(large_gaps.sum() / len(large_gaps)) if len(large_gaps) > 0 else 0.0
    else:
        gap_risk = 0.0

    return {
        "max_adverse_move": max_adverse_move,
        "downside_deviation": downside_deviation,
        "gap_risk": gap_risk,
    }
