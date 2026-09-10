"""
Data models for stock market data.

Uses Pydantic for runtime validation of all market data structures.
These models ensure data integrity before analysis begins.
"""

from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator


class StockUniverse(str, Enum):
    """Supported stock universe configurations."""
    NIFTY_50 = "NIFTY_50"
    NIFTY_100 = "NIFTY_100"
    NIFTY_200 = "NIFTY_200"
    NIFTY_500 = "NIFTY_500"
    CUSTOM = "CUSTOM"


class AnalysisPeriod(int, Enum):
    """Supported analysis periods in trading days."""
    DAYS_15 = 15
    DAYS_30 = 30


class DataProvider(str, Enum):
    """Supported data providers."""
    YFINANCE = "yfinance"
    OPENCHART = "openchart"


class OHLCVRecord(BaseModel):
    """
    Single OHLCV data point for a stock on a specific trading date.

    All prices are in INR (Indian Rupees).
    Timestamps are in IST (Indian Standard Time, UTC+5:30).
    """
    symbol: str = Field(..., description="NSE stock symbol (e.g., RELIANCE)")
    trading_date: date = Field(..., description="Trading session date")
    open: float = Field(..., gt=0, description="Opening price (INR)")
    high: float = Field(..., gt=0, description="Highest price (INR)")
    low: float = Field(..., gt=0, description="Lowest price (INR)")
    close: float = Field(..., gt=0, description="Closing price (INR)")
    volume: int = Field(..., ge=0, description="Trading volume (shares)")

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v, info):
        """High must be >= Low."""
        if "low" in info.data and v < info.data["low"]:
            raise ValueError(f"High ({v}) must be >= Low ({info.data['low']})")
        return v


class ValidationWarning(BaseModel):
    """A data quality warning for a specific stock or record."""
    symbol: str
    warning_type: str
    message: str
    severity: str = Field(default="WARNING", description="WARNING or ERROR")
    trading_date: Optional[date] = None


class ExcludedStock(BaseModel):
    """A stock excluded from analysis with a documented reason."""
    symbol: str
    reason: str
    details: Optional[str] = None


class StockMetrics(BaseModel):
    """
    Calculated metrics for a single stock over the analysis period.

    All formulas are documented in analysis/metrics.py.
    """
    symbol: str

    # Intraday Movement
    avg_hl_range_pct: float = Field(
        ..., description="Average (High-Low)/Low * 100 across all days"
    )
    avg_oc_move_pct: float = Field(
        ..., description="Average abs(Close-Open)/Open * 100 across all days"
    )
    median_hl_range_pct: float = Field(
        ..., description="Median (High-Low)/Low * 100 across all days"
    )
    avg_intraday_move_abs: float = Field(
        ..., description="Average absolute High-Low range in INR"
    )

    # Volatility
    daily_return_std: float = Field(
        ..., description="Std dev of daily close-to-close returns"
    )
    atr: float = Field(
        ..., description="Average True Range in INR"
    )
    normalized_atr: float = Field(
        ..., description="ATR / Close * 100 (percentage)"
    )

    # Volume / Liquidity
    avg_volume: float = Field(
        ..., description="Average daily volume"
    )
    volume_cv: float = Field(
        ..., description="Coefficient of variation of volume (std/mean)"
    )
    relative_volume_trend: float = Field(
        ..., description="Last 5 days avg volume / period avg volume"
    )

    # Consistency
    movement_frequency: float = Field(
        ..., description="Fraction of days with HL range > adaptive threshold"
    )
    max_consecutive_active_days: int = Field(
        ..., description="Longest streak of days with meaningful movement"
    )

    # Risk
    max_adverse_move: float = Field(
        ..., description="Maximum single-day absolute return"
    )
    downside_deviation: float = Field(
        ..., description="Std dev of negative daily returns"
    )
    gap_risk: float = Field(
        ..., description="Fraction of days with overnight gap > threshold"
    )

    # Metadata
    trading_days_analyzed: int = Field(
        ..., description="Number of valid trading days in dataset"
    )
    avg_close_price: float = Field(
        ..., description="Average closing price over period"
    )


class StockScore(BaseModel):
    """
    Scored stock with category sub-scores and final composite score.

    Every score is reproducible from the underlying StockMetrics.
    """
    symbol: str
    metrics: StockMetrics

    # Category scores (0-100 normalized)
    movement_score: float = Field(..., ge=0, le=100)
    volatility_score: float = Field(..., ge=0, le=100)
    liquidity_score: float = Field(..., ge=0, le=100)
    consistency_score: float = Field(..., ge=0, le=100)
    risk_penalty: float = Field(..., ge=0, le=100)

    # Final composite score
    final_score: float = Field(..., description="Weighted composite score")

    # Ranking explanation
    explanation: str = Field(
        default="",
        description="Human-readable explanation of why this stock received its score",
    )


class RankedStock(BaseModel):
    """A stock with its rank position and full scoring details."""
    rank: int = Field(..., ge=1)
    score: StockScore


class AnalysisResult(BaseModel):
    """
    Complete result of a stock analysis run.

    Contains all metadata needed for transparency and reproducibility.
    """
    # Ranking results
    top_stocks: List[RankedStock] = Field(
        ..., description="Top 5 ranked stocks (or fewer if insufficient data)"
    )

    # Metadata
    analysis_period_days: int = Field(
        ..., description="Number of trading days analyzed"
    )
    analysis_start_date: date
    analysis_end_date: date
    total_stocks_in_universe: int
    total_stocks_analyzed: int
    total_stocks_excluded: int
    excluded_stocks: List[ExcludedStock]
    data_provider: str
    data_retrieval_timestamp: datetime
    last_market_data_timestamp: Optional[date] = None
    scoring_methodology_version: str
    stock_universe: str

    # Warnings
    data_quality_warnings: List[ValidationWarning] = Field(default_factory=list)

    # All scores (for full transparency)
    all_scores: List[StockScore] = Field(
        default_factory=list,
        description="All scored stocks, not just top 5",
    )
