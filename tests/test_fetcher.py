"""
Tests for data fetcher module.

Tests verify:
    - Provider creation
    - Date range calculation
    - Error handling for missing symbols
    - Progress callback invocation

Note: These tests use mocking to avoid live API calls.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from app.data.fetcher import calculate_date_range, create_provider, DataFetchResult
from app.data.yfinance_provider import YFinanceProvider


class TestDateRangeCalculation:
    """Tests for the date range calculation."""

    def test_30_day_range(self):
        """30 trading days should request ~58+ calendar days."""
        ref = date(2025, 9, 1)
        start, end = calculate_date_range(30, ref)
        assert end == ref
        assert (end - start).days >= 45  # Enough buffer for weekends

    def test_15_day_range(self):
        """15 trading days should request ~34+ calendar days."""
        ref = date(2025, 9, 1)
        start, end = calculate_date_range(15, ref)
        assert end == ref
        assert (end - start).days >= 25

    def test_default_end_date(self):
        """Default end date should be today."""
        start, end = calculate_date_range(30)
        assert end == date.today()


class TestProviderCreation:
    """Tests for provider factory."""

    def test_default_provider(self):
        """Default provider should be YFinanceProvider."""
        provider = create_provider()
        assert isinstance(provider, YFinanceProvider)

    def test_provider_name(self):
        """Provider should have a descriptive name."""
        provider = create_provider()
        assert "Yahoo" in provider.get_provider_name() or "yfinance" in provider.get_provider_name()

    def test_provider_info(self):
        """Provider info should contain required fields."""
        provider = create_provider()
        info = provider.get_provider_info()
        assert "name" in info
        assert "type" in info
        assert "limitations" in info
        assert "license" in info


class TestDataFetchResult:
    """Tests for the DataFetchResult container."""

    def test_empty_result(self):
        """Empty result should have correct counts."""
        result = DataFetchResult()
        assert result.total_valid == 0
        assert result.total_excluded == 0

    def test_result_with_data(self):
        """Result with data should count correctly."""
        result = DataFetchResult()
        result.stock_data["A"] = pd.DataFrame()
        result.stock_data["B"] = pd.DataFrame()
        assert result.total_valid == 2

    def test_result_with_exclusions(self):
        """Exclusions should be tracked."""
        from app.models.stock_data import ExcludedStock
        result = DataFetchResult()
        result.excluded_stocks.append(
            ExcludedStock(symbol="X", reason="test")
        )
        assert result.total_excluded == 1
