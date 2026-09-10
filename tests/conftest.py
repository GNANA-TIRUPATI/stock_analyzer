"""
Shared test fixtures and deterministic sample data.

This module provides sample OHLCV data with known properties
so that metrics, scoring, and ranking can be tested without
requiring a live API connection.

ALL EXPECTED VALUES ARE HAND-COMPUTED AND DOCUMENTED.
"""

import sys
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def make_ohlcv_df(records: list, tz="Asia/Kolkata") -> pd.DataFrame:
    """
    Create a standardized OHLCV DataFrame from a list of dicts.

    Each dict should have: date, Open, High, Low, Close, Volume
    Returns a DataFrame with DatetimeIndex in IST.
    """
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["date"])
    df = df.set_index("Date")
    df.index = df.index.tz_localize(tz)
    df = df.drop(columns=["date"])
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    return df


@pytest.fixture
def sample_stock_a():
    """
    Stock A: HIGH MOVEMENT, HIGH VOLUME — should rank well.

    10 trading days with consistently high HL range (~3-4%) and high volume.
    """
    records = [
        {"date": "2025-08-01", "Open": 100, "High": 104, "Low": 99, "Close": 103, "Volume": 5000000},
        {"date": "2025-08-04", "Open": 103, "High": 107, "Low": 102, "Close": 106, "Volume": 5200000},
        {"date": "2025-08-05", "Open": 106, "High": 110, "Low": 105, "Close": 108, "Volume": 4800000},
        {"date": "2025-08-06", "Open": 108, "High": 112, "Low": 107, "Close": 111, "Volume": 5100000},
        {"date": "2025-08-07", "Open": 111, "High": 115, "Low": 109, "Close": 113, "Volume": 4900000},
        {"date": "2025-08-08", "Open": 113, "High": 117, "Low": 112, "Close": 116, "Volume": 5300000},
        {"date": "2025-08-11", "Open": 116, "High": 120, "Low": 114, "Close": 118, "Volume": 5000000},
        {"date": "2025-08-12", "Open": 118, "High": 122, "Low": 116, "Close": 120, "Volume": 4700000},
        {"date": "2025-08-13", "Open": 120, "High": 124, "Low": 118, "Close": 122, "Volume": 5100000},
        {"date": "2025-08-14", "Open": 122, "High": 126, "Low": 120, "Close": 124, "Volume": 5400000},
    ]
    return make_ohlcv_df(records)


@pytest.fixture
def sample_stock_b():
    """
    Stock B: LOW MOVEMENT, HIGH VOLUME — should rank lower.

    10 trading days with narrow HL range (~1%) but decent volume.
    """
    records = [
        {"date": "2025-08-01", "Open": 500, "High": 505, "Low": 498, "Close": 503, "Volume": 8000000},
        {"date": "2025-08-04", "Open": 503, "High": 507, "Low": 501, "Close": 505, "Volume": 7800000},
        {"date": "2025-08-05", "Open": 505, "High": 509, "Low": 503, "Close": 507, "Volume": 8200000},
        {"date": "2025-08-06", "Open": 507, "High": 510, "Low": 505, "Close": 509, "Volume": 7900000},
        {"date": "2025-08-07", "Open": 509, "High": 512, "Low": 507, "Close": 510, "Volume": 8100000},
        {"date": "2025-08-08", "Open": 510, "High": 514, "Low": 508, "Close": 512, "Volume": 8300000},
        {"date": "2025-08-11", "Open": 512, "High": 515, "Low": 510, "Close": 513, "Volume": 7700000},
        {"date": "2025-08-12", "Open": 513, "High": 516, "Low": 511, "Close": 514, "Volume": 8000000},
        {"date": "2025-08-13", "Open": 514, "High": 517, "Low": 512, "Close": 515, "Volume": 8400000},
        {"date": "2025-08-14", "Open": 515, "High": 518, "Low": 513, "Close": 516, "Volume": 8100000},
    ]
    return make_ohlcv_df(records)


@pytest.fixture
def sample_stock_c():
    """
    Stock C: HIGH MOVEMENT BUT INCONSISTENT — one spike day.

    9 days of low movement + 1 extreme day. Should be penalized for inconsistency.
    """
    records = [
        {"date": "2025-08-01", "Open": 200, "High": 202, "Low": 199, "Close": 201, "Volume": 3000000},
        {"date": "2025-08-04", "Open": 201, "High": 203, "Low": 200, "Close": 202, "Volume": 3100000},
        {"date": "2025-08-05", "Open": 202, "High": 204, "Low": 201, "Close": 203, "Volume": 2900000},
        {"date": "2025-08-06", "Open": 203, "High": 205, "Low": 202, "Close": 204, "Volume": 3200000},
        {"date": "2025-08-07", "Open": 204, "High": 206, "Low": 203, "Close": 205, "Volume": 2800000},
        {"date": "2025-08-08", "Open": 205, "High": 230, "Low": 195, "Close": 220, "Volume": 15000000},  # SPIKE
        {"date": "2025-08-11", "Open": 220, "High": 222, "Low": 218, "Close": 221, "Volume": 3500000},
        {"date": "2025-08-12", "Open": 221, "High": 223, "Low": 220, "Close": 222, "Volume": 3000000},
        {"date": "2025-08-13", "Open": 222, "High": 224, "Low": 221, "Close": 223, "Volume": 3100000},
        {"date": "2025-08-14", "Open": 223, "High": 225, "Low": 222, "Close": 224, "Volume": 3200000},
    ]
    return make_ohlcv_df(records)


@pytest.fixture
def sample_invalid_data():
    """
    Invalid data with various quality issues for testing validation.

    Issues: High < Low on day 2, zero volume on day 3, negative price on day 4.
    """
    records = [
        {"date": "2025-08-01", "Open": 100, "High": 105, "Low": 98,  "Close": 103, "Volume": 1000000},
        {"date": "2025-08-04", "Open": 103, "High": 100, "Low": 105, "Close": 102, "Volume": 1100000},  # High < Low
        {"date": "2025-08-05", "Open": 102, "High": 106, "Low": 101, "Close": 105, "Volume": 0},        # Zero volume
        {"date": "2025-08-06", "Open": -10, "High": 108, "Low": 102, "Close": 107, "Volume": 900000},   # Negative price
        {"date": "2025-08-07", "Open": 107, "High": 110, "Low": 105, "Close": 109, "Volume": 1200000},
    ]
    return make_ohlcv_df(records)


@pytest.fixture
def sample_duplicate_data():
    """Data with duplicate timestamps."""
    records = [
        {"date": "2025-08-01", "Open": 100, "High": 105, "Low": 98, "Close": 103, "Volume": 1000000},
        {"date": "2025-08-01", "Open": 101, "High": 106, "Low": 99, "Close": 104, "Volume": 1100000},  # Duplicate
        {"date": "2025-08-04", "Open": 103, "High": 107, "Low": 101, "Close": 106, "Volume": 1200000},
    ]
    return make_ohlcv_df(records)


@pytest.fixture
def sample_gap_data():
    """Data with a large overnight gap (>20%) suggesting corporate action."""
    records = [
        {"date": "2025-08-01", "Open": 100, "High": 105, "Low": 98,  "Close": 103, "Volume": 1000000},
        {"date": "2025-08-04", "Open": 103, "High": 107, "Low": 101, "Close": 106, "Volume": 1100000},
        {"date": "2025-08-05", "Open": 50,  "High": 55,  "Low": 48,  "Close": 53,  "Volume": 5000000},  # 50% gap (split?)
        {"date": "2025-08-06", "Open": 53,  "High": 56,  "Low": 51,  "Close": 55,  "Volume": 4000000},
        {"date": "2025-08-07", "Open": 55,  "High": 58,  "Low": 53,  "Close": 57,  "Volume": 3500000},
    ]
    return make_ohlcv_df(records)
