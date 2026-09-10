"""
Ranking module — produces the final Top 5 ranking.

Takes scored stocks and produces a deterministic, reproducible ranking.
Ties are broken by secondary criteria (higher avg volume wins).

The ranking process:
    1. Sort all scored stocks by final_score descending
    2. Break ties using avg_volume (higher volume preferred)
    3. Select Top 5 (or fewer if insufficient valid stocks)
    4. Assign rank numbers 1-5
    5. Update explanations with rank position

IMPORTANT:
    - This is a HISTORICAL analysis, not a prediction.
    - Rankings reflect past characteristics only.
    - No guarantees of future profitability are implied.
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from app.analysis.metrics import calculate_metrics
from app.analysis.scoring import StockScorer
from app.config.settings import get_scoring_weights
from app.data.fetcher import DataFetchResult
from app.models.stock_data import (
    AnalysisResult,
    RankedStock,
    StockMetrics,
    StockScore,
)

logger = logging.getLogger(__name__)

TOP_N = 5  # Number of top stocks to return


def rank_stocks(
    fetch_result: DataFetchResult,
    analysis_period: int,
    stock_universe: str,
) -> AnalysisResult:
    """
    Complete ranking pipeline: metrics → scoring → ranking → result.

    Args:
        fetch_result: Result from data fetcher containing validated stock data
        analysis_period: Number of trading days in the analysis window
        stock_universe: Name of the stock universe used

    Returns:
        AnalysisResult with Top 5 ranked stocks and full metadata
    """
    scoring_weights = get_scoring_weights()

    # Step 1: Calculate metrics for all valid stocks
    logger.info(f"Calculating metrics for {len(fetch_result.stock_data)} stocks...")
    metrics_list: List[StockMetrics] = []
    metrics_failures = 0

    for symbol, df in fetch_result.stock_data.items():
        metrics = calculate_metrics(symbol, df)
        if metrics is not None:
            metrics_list.append(metrics)
        else:
            metrics_failures += 1
            logger.warning(f"Metrics calculation failed for {symbol}")

    logger.info(
        f"Metrics calculated: {len(metrics_list)} succeeded, "
        f"{metrics_failures} failed"
    )

    if len(metrics_list) == 0:
        logger.error("No stocks have valid metrics. Cannot produce ranking.")
        return _empty_result(fetch_result, analysis_period, stock_universe, scoring_weights)

    # Step 2: Score all stocks
    logger.info("Scoring stocks...")
    scorer = StockScorer(scoring_weights)
    all_scores = scorer.score_stocks(metrics_list)

    # Step 3: Sort by final_score descending, break ties by avg_volume
    sorted_scores = sorted(
        all_scores,
        key=lambda s: (s.final_score, s.metrics.avg_volume),
        reverse=True,
    )

    # Step 4: Select Top N
    top_n = min(TOP_N, len(sorted_scores))
    top_stocks: List[RankedStock] = []

    for i, score in enumerate(sorted_scores[:top_n]):
        rank = i + 1

        # Update explanation with rank context
        rank_explanation = (
            f"Ranked #{rank} because its historical data showed "
            f"{_get_rank_reason(score)}."
        )
        score.explanation = rank_explanation

        top_stocks.append(RankedStock(rank=rank, score=score))

    # Step 5: Determine analysis date range
    all_dates = []
    for df in fetch_result.stock_data.values():
        if hasattr(df.index, 'date'):
            all_dates.extend([d.date() for d in df.index])
        else:
            all_dates.extend(df.index.tolist())

    analysis_start = min(all_dates) if all_dates else date.today()
    analysis_end = max(all_dates) if all_dates else date.today()

    # Build result
    result = AnalysisResult(
        top_stocks=top_stocks,
        analysis_period_days=analysis_period,
        analysis_start_date=analysis_start,
        analysis_end_date=analysis_end,
        total_stocks_in_universe=fetch_result.total_universe_size,
        total_stocks_analyzed=len(metrics_list),
        total_stocks_excluded=fetch_result.total_excluded + metrics_failures,
        excluded_stocks=fetch_result.excluded_stocks,
        data_provider=fetch_result.provider_name,
        data_retrieval_timestamp=fetch_result.fetch_timestamp,
        last_market_data_timestamp=fetch_result.last_market_data_date,
        scoring_methodology_version=scoring_weights.version,
        stock_universe=stock_universe,
        data_quality_warnings=fetch_result.warnings,
        all_scores=sorted_scores,
    )

    logger.info(
        f"Ranking complete. Top {top_n} stocks identified from "
        f"{len(metrics_list)} analyzed."
    )

    return result


def _get_rank_reason(score: StockScore) -> str:
    """
    Generate a concise reason for the stock's ranking position.

    Based on which category scores are strongest relative to others.
    """
    categories = {
        "high average intraday movement": score.movement_score,
        "strong liquidity": score.liquidity_score,
        "notable historical volatility": score.volatility_score,
        "consistent movement patterns": score.consistency_score,
    }

    # Sort by score
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)

    # Take top 2-3 contributing factors
    reasons = []
    for name, val in sorted_cats:
        if val >= 30:  # Only include meaningful contributions
            reasons.append(name)
        if len(reasons) >= 3:
            break

    if not reasons:
        reasons = ["balanced characteristics across all metrics"]

    # Add risk note if penalty is high
    if score.risk_penalty > 60:
        return (
            f"{', '.join(reasons[:-1])}, and {reasons[-1]}, "
            f"despite elevated risk characteristics during the analyzed period"
        )

    return ", ".join(reasons[:-1]) + f", and {reasons[-1]}" if len(reasons) > 1 else reasons[0]


def _empty_result(
    fetch_result: DataFetchResult,
    analysis_period: int,
    stock_universe: str,
    scoring_weights,
) -> AnalysisResult:
    """Create an empty result when no stocks could be analyzed."""
    return AnalysisResult(
        top_stocks=[],
        analysis_period_days=analysis_period,
        analysis_start_date=date.today(),
        analysis_end_date=date.today(),
        total_stocks_in_universe=fetch_result.total_universe_size,
        total_stocks_analyzed=0,
        total_stocks_excluded=fetch_result.total_excluded,
        excluded_stocks=fetch_result.excluded_stocks,
        data_provider=fetch_result.provider_name,
        data_retrieval_timestamp=fetch_result.fetch_timestamp,
        last_market_data_timestamp=None,
        scoring_methodology_version=scoring_weights.version,
        stock_universe=stock_universe,
        data_quality_warnings=fetch_result.warnings,
        all_scores=[],
    )
