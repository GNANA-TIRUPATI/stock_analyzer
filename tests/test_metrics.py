"""
Tests for metrics calculation module.

Tests verify that each metric formula produces correct results
using deterministic sample data with hand-computed expected values.
"""

import numpy as np
import pandas as pd
import pytest

from app.analysis.metrics import (
    calculate_metrics,
    _calculate_movement_metrics,
    _calculate_volatility_metrics,
    _calculate_liquidity_metrics,
    _calculate_consistency_metrics,
    _calculate_risk_metrics,
    _max_consecutive_true,
)


class TestMovementMetrics:
    """Tests for intraday price movement calculations."""

    def test_hl_range_pct(self, sample_stock_a):
        """
        Verify High-Low range percentage calculation.

        Day 1: (104-99)/99 × 100 = 5.05%
        Day 2: (107-102)/102 × 100 = 4.90%
        Average should be ~4.9-5.1% for stock A.
        """
        result = _calculate_movement_metrics(sample_stock_a)
        assert result["avg_hl_range_pct"] > 4.0
        assert result["avg_hl_range_pct"] < 6.0

    def test_oc_move_pct(self, sample_stock_a):
        """
        Verify Open-to-Close movement percentage.

        Day 1: |103-100|/100 × 100 = 3.0%
        All days should show ~2-3% OC movement.
        """
        result = _calculate_movement_metrics(sample_stock_a)
        assert result["avg_oc_move_pct"] > 1.0
        assert result["avg_oc_move_pct"] < 5.0

    def test_median_vs_mean(self, sample_stock_c):
        """
        Stock C has one spike day. Median should be lower than mean.

        The spike day has HL range of (230-195)/195 × 100 = 17.95%
        Other days have ~1.5% range. Median should be close to 1.5%.
        """
        result = _calculate_movement_metrics(sample_stock_c)
        assert result["median_hl_range_pct"] < result["avg_hl_range_pct"]

    def test_abs_movement(self, sample_stock_a):
        """Absolute movement should be in INR terms."""
        result = _calculate_movement_metrics(sample_stock_a)
        # Day 1: 104-99 = 5, Day 2: 107-102 = 5, etc.
        assert result["avg_intraday_move_abs"] > 0


class TestVolatilityMetrics:
    """Tests for volatility calculations."""

    def test_daily_return_std(self, sample_stock_a):
        """Daily return std should be positive and reasonable."""
        result = _calculate_volatility_metrics(sample_stock_a)
        assert result["daily_return_std"] > 0
        assert result["daily_return_std"] < 1  # Should be a fraction

    def test_atr_positive(self, sample_stock_a):
        """ATR must be positive."""
        result = _calculate_volatility_metrics(sample_stock_a)
        assert result["atr"] > 0

    def test_normalized_atr(self, sample_stock_a):
        """Normalized ATR should be a percentage."""
        result = _calculate_volatility_metrics(sample_stock_a)
        assert result["normalized_atr"] > 0
        assert result["normalized_atr"] < 100

    def test_spike_increases_volatility(self, sample_stock_b, sample_stock_c):
        """Stock C (spike) should have higher volatility than Stock B (stable)."""
        vol_b = _calculate_volatility_metrics(sample_stock_b)
        vol_c = _calculate_volatility_metrics(sample_stock_c)
        assert vol_c["daily_return_std"] > vol_b["daily_return_std"]


class TestLiquidityMetrics:
    """Tests for volume and liquidity calculations."""

    def test_avg_volume(self, sample_stock_a):
        """Average volume should match expected range."""
        result = _calculate_liquidity_metrics(sample_stock_a)
        # Stock A has volumes around 5M
        assert 4_000_000 < result["avg_volume"] < 6_000_000

    def test_volume_cv_positive(self, sample_stock_a):
        """Coefficient of variation should be positive."""
        result = _calculate_liquidity_metrics(sample_stock_a)
        assert result["volume_cv"] >= 0

    def test_relative_volume_trend(self, sample_stock_a):
        """Relative volume trend should be around 1.0 for consistent volume."""
        result = _calculate_liquidity_metrics(sample_stock_a)
        # Stock A has relatively consistent volume
        assert 0.5 < result["relative_volume_trend"] < 2.0

    def test_zero_volume_handling(self):
        """All-zero volume should return zero metrics."""
        from tests.conftest import make_ohlcv_df
        records = [
            {"date": "2025-08-01", "Open": 100, "High": 105, "Low": 98, "Close": 103, "Volume": 0},
            {"date": "2025-08-04", "Open": 103, "High": 107, "Low": 101, "Close": 106, "Volume": 0},
        ]
        df = make_ohlcv_df(records)
        result = _calculate_liquidity_metrics(df)
        assert result["avg_volume"] == 0.0


class TestConsistencyMetrics:
    """Tests for movement consistency calculations."""

    def test_high_consistency_stock(self, sample_stock_a):
        """Stock A with consistent movement should have high frequency."""
        movement = _calculate_movement_metrics(sample_stock_a)
        result = _calculate_consistency_metrics(
            sample_stock_a, movement["hl_range_pct_series"]
        )
        # Most days should be "active" (above threshold)
        assert result["movement_frequency"] > 0.5

    def test_max_consecutive_true_basic(self):
        """Test consecutive True counting."""
        s = pd.Series([True, True, True, False, True, True])
        assert _max_consecutive_true(s) == 3

    def test_max_consecutive_true_all_true(self):
        """All True should return full length."""
        s = pd.Series([True, True, True, True])
        assert _max_consecutive_true(s) == 4

    def test_max_consecutive_true_empty(self):
        """Empty series should return 0."""
        s = pd.Series([], dtype=bool)
        assert _max_consecutive_true(s) == 0

    def test_max_consecutive_true_all_false(self):
        """All False should return 0."""
        s = pd.Series([False, False, False])
        assert _max_consecutive_true(s) == 0


class TestRiskMetrics:
    """Tests for risk characteristic calculations."""

    def test_max_adverse_move(self, sample_stock_c):
        """Stock C spike should show high max adverse move."""
        result = _calculate_risk_metrics(sample_stock_c)
        # The spike day has ~7% return, so max_adverse should be significant
        assert result["max_adverse_move"] > 0.05

    def test_downside_deviation(self, sample_stock_a):
        """Downside deviation should be non-negative."""
        result = _calculate_risk_metrics(sample_stock_a)
        assert result["downside_deviation"] >= 0

    def test_gap_risk(self, sample_stock_a):
        """Stock A has no large gaps, so gap risk should be low."""
        result = _calculate_risk_metrics(sample_stock_a)
        assert result["gap_risk"] < 0.5


class TestFullMetricsCalculation:
    """Tests for the complete calculate_metrics function."""

    def test_full_metrics_returns_model(self, sample_stock_a):
        """Full calculation should return a valid StockMetrics model."""
        metrics = calculate_metrics("TEST_A", sample_stock_a)
        assert metrics is not None
        assert metrics.symbol == "TEST_A"
        assert metrics.trading_days_analyzed == 10

    def test_insufficient_data_returns_none(self):
        """Less than 2 rows should return None."""
        from tests.conftest import make_ohlcv_df
        records = [
            {"date": "2025-08-01", "Open": 100, "High": 105, "Low": 98, "Close": 103, "Volume": 1000000},
        ]
        df = make_ohlcv_df(records)
        metrics = calculate_metrics("SINGLE", df)
        assert metrics is None

    def test_none_data_returns_none(self):
        """None input should return None."""
        metrics = calculate_metrics("NULL", None)
        assert metrics is None
