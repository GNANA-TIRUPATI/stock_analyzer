"""
Tests for data validation engine.

Tests cover:
    - Valid OHLC acceptance
    - High < Low detection
    - Zero/negative price detection
    - Duplicate timestamp handling
    - Zero volume detection
    - Suspicious gap detection
    - Insufficient sessions exclusion
    - Missing column exclusion
"""

import pandas as pd
import pytest

from app.data.validator import DataValidator
from app.config.settings import get_scoring_weights


@pytest.fixture
def validator():
    """Create validator with default thresholds."""
    return DataValidator()


class TestOHLCValidation:
    """Tests for OHLC relationship validation."""

    def test_valid_data_passes(self, validator, sample_stock_a):
        """Valid data should pass all checks."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "TEST_A", sample_stock_a, expected_trading_days=10
        )
        assert cleaned is not None
        assert exclusion is None
        assert len(cleaned) == 10

    def test_high_less_than_low_removed(self, validator, sample_invalid_data):
        """Rows where High < Low should be removed."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "TEST_INVALID", sample_invalid_data, expected_trading_days=5
        )
        # Check that the High < Low warning was generated
        hl_warnings = [
            w for w in warnings if w.warning_type == "HIGH_LESS_THAN_LOW"
        ]
        assert len(hl_warnings) > 0

    def test_negative_price_removed(self, validator, sample_invalid_data):
        """Rows with negative prices should be removed."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "TEST_INVALID", sample_invalid_data, expected_trading_days=5
        )
        price_warnings = [
            w for w in warnings if w.warning_type == "INVALID_PRICE"
        ]
        assert len(price_warnings) > 0

    def test_empty_data_excluded(self, validator):
        """Empty DataFrame should result in exclusion."""
        empty_df = pd.DataFrame()
        cleaned, warnings, exclusion = validator.validate_stock(
            "EMPTY", empty_df, expected_trading_days=10
        )
        assert cleaned is None
        assert exclusion is not None
        assert "No data" in exclusion.reason

    def test_none_data_excluded(self, validator):
        """None data should result in exclusion."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "NONE", None, expected_trading_days=10
        )
        assert cleaned is None
        assert exclusion is not None


class TestDuplicateHandling:
    """Tests for duplicate timestamp detection."""

    def test_duplicates_removed(self, validator, sample_duplicate_data):
        """Duplicate timestamps should be removed (keep first)."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "DUP", sample_duplicate_data, expected_trading_days=2
        )
        dup_warnings = [
            w for w in warnings if w.warning_type == "DUPLICATE_TIMESTAMPS"
        ]
        assert len(dup_warnings) > 0
        if cleaned is not None:
            assert not cleaned.index.duplicated().any()


class TestVolumeValidation:
    """Tests for volume-related validation."""

    def test_zero_volume_warned(self, validator, sample_invalid_data):
        """Zero volume days should generate warnings."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "TEST_VOL", sample_invalid_data, expected_trading_days=5
        )
        vol_warnings = [
            w for w in warnings if w.warning_type == "ZERO_VOLUME"
        ]
        assert len(vol_warnings) > 0


class TestGapDetection:
    """Tests for suspicious gap detection."""

    def test_large_gap_detected(self, validator, sample_gap_data):
        """Large overnight gaps (>20%) should generate warnings."""
        cleaned, warnings, exclusion = validator.validate_stock(
            "GAP", sample_gap_data, expected_trading_days=5
        )
        gap_warnings = [
            w for w in warnings if w.warning_type == "SUSPICIOUS_GAP"
        ]
        assert len(gap_warnings) > 0
        assert "corporate action" in gap_warnings[0].message.lower()


class TestInsufficientSessions:
    """Tests for session coverage validation."""

    def test_insufficient_sessions_excluded(self, validator, sample_stock_a):
        """Stock with too few sessions should be excluded."""
        # Only provide 10 days but claim to need 30
        # 10/30 = 33% < 80% threshold
        cleaned, warnings, exclusion = validator.validate_stock(
            "INSUFF", sample_stock_a, expected_trading_days=30
        )
        assert exclusion is not None
        assert "Insufficient" in exclusion.reason


class TestMissingColumns:
    """Tests for missing data column handling."""

    def test_missing_columns_excluded(self, validator):
        """DataFrame missing required columns should be excluded."""
        df = pd.DataFrame({"Open": [100], "High": [105]})
        df.index = pd.to_datetime(["2025-08-01"])
        df.index = df.index.tz_localize("Asia/Kolkata")

        cleaned, warnings, exclusion = validator.validate_stock(
            "MISSING_COL", df, expected_trading_days=1
        )
        assert exclusion is not None
        assert "Missing" in exclusion.reason
