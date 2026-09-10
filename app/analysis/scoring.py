"""
Scoring module — normalizes metrics and computes composite scores.

SCORING MODEL:
    Final Score = (Movement_Score × 0.30)
                + (Volatility_Score × 0.20)
                + (Liquidity_Score × 0.25)
                + (Consistency_Score × 0.15)
                - (Risk_Penalty × 0.10)

NORMALIZATION METHOD:
    Min-Max normalization to [0, 100] across all eligible stocks:
        normalized = (value - min) / (max - min) × 100

    For inverse metrics (lower is better, e.g., Volume CV):
        normalized = (1 - (value - min) / (max - min)) × 100

All weights are loaded from scoring_weights.yaml and are configurable.
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from app.config.settings import ScoringWeights, get_scoring_weights
from app.models.stock_data import StockMetrics, StockScore

logger = logging.getLogger(__name__)


class StockScorer:
    """
    Scores stocks based on their metrics using configurable weights.

    The scorer:
        1. Collects raw metric values across all stocks
        2. Normalizes each metric to [0, 100] using min-max
        3. Combines normalized metrics into category scores
        4. Combines category scores into a final composite score
        5. Generates human-readable explanations
    """

    def __init__(self, weights: Optional[ScoringWeights] = None):
        """
        Initialize scorer with configurable weights.

        Args:
            weights: ScoringWeights from YAML config. If None, loads defaults.
        """
        if weights is None:
            weights = get_scoring_weights()
        self._weights = weights

    def score_stocks(self, metrics_list: List[StockMetrics]) -> List[StockScore]:
        """
        Score all stocks using their computed metrics.

        Args:
            metrics_list: List of StockMetrics for all eligible stocks.
                Must contain at least 2 stocks for meaningful normalization.

        Returns:
            List of StockScore objects with normalized scores.
        """
        if len(metrics_list) == 0:
            return []

        if len(metrics_list) == 1:
            # Single stock: all normalized values are 50 (midpoint)
            return [self._score_single_stock(metrics_list[0])]

        # Step 1: Extract raw metric values for normalization
        raw_values = self._extract_raw_values(metrics_list)

        # Step 2: Compute min/max for each metric
        ranges = self._compute_ranges(raw_values)

        # Step 3: Score each stock
        scores = []
        for metrics in metrics_list:
            score = self._compute_score(metrics, ranges)
            scores.append(score)

        logger.info(f"Scored {len(scores)} stocks")
        return scores

    def _extract_raw_values(
        self, metrics_list: List[StockMetrics]
    ) -> Dict[str, List[float]]:
        """Extract raw metric values across all stocks for normalization."""
        fields = [
            "avg_hl_range_pct", "avg_oc_move_pct", "median_hl_range_pct",
            "normalized_atr", "daily_return_std",
            "avg_volume", "volume_cv", "relative_volume_trend",
            "movement_frequency", "max_consecutive_active_days",
            "max_adverse_move", "downside_deviation", "gap_risk",
        ]

        raw_values = {}
        for field in fields:
            raw_values[field] = [getattr(m, field) for m in metrics_list]

        return raw_values

    def _compute_ranges(
        self, raw_values: Dict[str, List[float]]
    ) -> Dict[str, Dict[str, float]]:
        """Compute min and max for each metric across all stocks."""
        ranges = {}
        for field, values in raw_values.items():
            min_val = min(values)
            max_val = max(values)
            ranges[field] = {"min": min_val, "max": max_val}
        return ranges

    def _normalize(
        self,
        value: float,
        min_val: float,
        max_val: float,
        inverse: bool = False,
    ) -> float:
        """
        Min-max normalize a value to [0, 100].

        Args:
            value: Raw metric value
            min_val: Minimum across all stocks
            max_val: Maximum across all stocks
            inverse: If True, higher raw values get lower normalized scores

        Returns:
            Normalized value in [0, 100]

        Formula:
            Normal:  (value - min) / (max - min) × 100
            Inverse: (1 - (value - min) / (max - min)) × 100
        """
        if max_val == min_val:
            return 50.0  # All stocks equal: assign midpoint

        normalized = (value - min_val) / (max_val - min_val) * 100

        if inverse:
            normalized = 100.0 - normalized

        # Clamp to [0, 100] for safety
        return max(0.0, min(100.0, normalized))

    def _compute_score(
        self,
        metrics: StockMetrics,
        ranges: Dict[str, Dict[str, float]],
    ) -> StockScore:
        """
        Compute the full composite score for a single stock.

        Steps:
            1. Normalize each raw metric
            2. Combine into category scores using sub-metric weights
            3. Combine categories into final score using category weights
        """
        cat_w = self._weights.category_weights
        mov_w = self._weights.movement_weights
        vol_w = self._weights.volatility_weights
        liq_w = self._weights.liquidity_weights
        con_w = self._weights.consistency_weights
        risk_w = self._weights.risk_penalty_weights

        # ----- MOVEMENT SCORE -----
        # Higher movement = better for day trading
        n_avg_hl = self._normalize(
            metrics.avg_hl_range_pct,
            ranges["avg_hl_range_pct"]["min"],
            ranges["avg_hl_range_pct"]["max"],
        )
        n_avg_oc = self._normalize(
            metrics.avg_oc_move_pct,
            ranges["avg_oc_move_pct"]["min"],
            ranges["avg_oc_move_pct"]["max"],
        )
        n_med_hl = self._normalize(
            metrics.median_hl_range_pct,
            ranges["median_hl_range_pct"]["min"],
            ranges["median_hl_range_pct"]["max"],
        )
        movement_score = (
            mov_w["avg_hl_range_pct"] * n_avg_hl
            + mov_w["avg_oc_move_pct"] * n_avg_oc
            + mov_w["median_hl_range_pct"] * n_med_hl
        )

        # ----- VOLATILITY SCORE -----
        # Higher volatility = more day-trading opportunity
        n_natr = self._normalize(
            metrics.normalized_atr,
            ranges["normalized_atr"]["min"],
            ranges["normalized_atr"]["max"],
        )
        n_ret_std = self._normalize(
            metrics.daily_return_std,
            ranges["daily_return_std"]["min"],
            ranges["daily_return_std"]["max"],
        )
        volatility_score = (
            vol_w["normalized_atr"] * n_natr
            + vol_w["daily_return_std"] * n_ret_std
        )

        # ----- LIQUIDITY SCORE -----
        # Higher volume = better; Lower CV = better (inverse)
        n_avg_vol = self._normalize(
            metrics.avg_volume,
            ranges["avg_volume"]["min"],
            ranges["avg_volume"]["max"],
        )
        n_vol_cv = self._normalize(
            metrics.volume_cv,
            ranges["volume_cv"]["min"],
            ranges["volume_cv"]["max"],
            inverse=True,  # Lower CV = more consistent = better
        )
        n_rel_vol = self._normalize(
            metrics.relative_volume_trend,
            ranges["relative_volume_trend"]["min"],
            ranges["relative_volume_trend"]["max"],
        )
        liquidity_score = (
            liq_w["avg_volume"] * n_avg_vol
            + liq_w["volume_consistency"] * n_vol_cv
            + liq_w["relative_volume_trend"] * n_rel_vol
        )

        # ----- CONSISTENCY SCORE -----
        # Higher frequency and streaks = better
        n_mov_freq = self._normalize(
            metrics.movement_frequency,
            ranges["movement_frequency"]["min"],
            ranges["movement_frequency"]["max"],
        )
        n_streak = self._normalize(
            metrics.max_consecutive_active_days,
            ranges["max_consecutive_active_days"]["min"],
            ranges["max_consecutive_active_days"]["max"],
        )
        consistency_score = (
            con_w["movement_frequency"] * n_mov_freq
            + con_w["streak_length"] * n_streak
        )

        # ----- RISK PENALTY -----
        # Higher risk metrics = higher penalty
        n_max_adv = self._normalize(
            metrics.max_adverse_move,
            ranges["max_adverse_move"]["min"],
            ranges["max_adverse_move"]["max"],
        )
        n_down_dev = self._normalize(
            metrics.downside_deviation,
            ranges["downside_deviation"]["min"],
            ranges["downside_deviation"]["max"],
        )
        n_gap = self._normalize(
            metrics.gap_risk,
            ranges["gap_risk"]["min"],
            ranges["gap_risk"]["max"],
        )
        risk_penalty = (
            risk_w["max_adverse_move"] * n_max_adv
            + risk_w["downside_deviation"] * n_down_dev
            + risk_w["gap_risk"] * n_gap
        )

        # ----- FINAL COMPOSITE SCORE -----
        final_score = (
            cat_w["movement"] * movement_score
            + cat_w["volatility"] * volatility_score
            + cat_w["liquidity"] * liquidity_score
            + cat_w["consistency"] * consistency_score
            - cat_w["risk_penalty"] * risk_penalty
        )

        # Generate explanation
        explanation = self._generate_explanation(
            metrics, movement_score, volatility_score,
            liquidity_score, consistency_score, risk_penalty,
        )

        return StockScore(
            symbol=metrics.symbol,
            metrics=metrics,
            movement_score=round(movement_score, 2),
            volatility_score=round(volatility_score, 2),
            liquidity_score=round(liquidity_score, 2),
            consistency_score=round(consistency_score, 2),
            risk_penalty=round(risk_penalty, 2),
            final_score=round(final_score, 2),
            explanation=explanation,
        )

    def _score_single_stock(self, metrics: StockMetrics) -> StockScore:
        """Score a single stock when only one is available (all scores = 50)."""
        return StockScore(
            symbol=metrics.symbol,
            metrics=metrics,
            movement_score=50.0,
            volatility_score=50.0,
            liquidity_score=50.0,
            consistency_score=50.0,
            risk_penalty=50.0,
            final_score=50.0,
            explanation=(
                f"{metrics.symbol}: Only one stock available for analysis. "
                f"Comparative scoring not possible."
            ),
        )

    def _generate_explanation(
        self,
        metrics: StockMetrics,
        movement: float,
        volatility: float,
        liquidity: float,
        consistency: float,
        risk: float,
    ) -> str:
        """
        Generate a human-readable explanation for the stock's ranking.

        IMPORTANT: This is a factual description of historical characteristics.
        It does NOT predict future performance or guarantee profits.
        """
        parts = []

        # Identify strongest category
        categories = {
            "high average intraday movement": movement,
            "notable historical volatility": volatility,
            "strong trading liquidity": liquidity,
            "consistent daily price activity": consistency,
        }

        # Sort by score descending
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)

        # Top 2 strengths
        strengths = [name for name, score in sorted_cats[:2] if score >= 40]
        if strengths:
            parts.append(
                f"Historical data showed {', '.join(strengths)}"
            )

        # Key metrics
        freq_str = (
            "active in all sessions"
            if metrics.movement_frequency >= 0.995
            else f"active {metrics.movement_frequency:.0%} of sessions"
        )
        parts.append(
            f"(avg range: {metrics.avg_hl_range_pct:.2f}%, "
            f"avg volume: {metrics.avg_volume:,.0f}, "
            f"{freq_str})"
        )

        # Risk note if significant
        if risk > 60:
            parts.append(
                "Note: elevated risk characteristics observed in the analysis period."
            )

        explanation = ". ".join(parts) + "."

        return explanation
