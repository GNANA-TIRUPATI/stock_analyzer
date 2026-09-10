"""
Tests for scoring module.

Tests verify:
    - Min-max normalization correctness
    - Inverse normalization for metrics where lower is better
    - Category score composition
    - Final score calculation
    - Single-stock edge case
    - Weight application
"""

import pytest

from app.analysis.metrics import calculate_metrics
from app.analysis.scoring import StockScorer
from app.config.settings import get_scoring_weights


@pytest.fixture
def scorer():
    """Create scorer with default weights."""
    return StockScorer()


@pytest.fixture
def three_stock_metrics(sample_stock_a, sample_stock_b, sample_stock_c):
    """Calculate metrics for all three sample stocks."""
    m_a = calculate_metrics("STOCK_A", sample_stock_a)
    m_b = calculate_metrics("STOCK_B", sample_stock_b)
    m_c = calculate_metrics("STOCK_C", sample_stock_c)
    return [m_a, m_b, m_c]


class TestNormalization:
    """Tests for min-max normalization."""

    def test_normalize_basic(self, scorer):
        """Basic normalization: value at min=0, max=100, mid=50."""
        assert scorer._normalize(0, 0, 100) == 0.0
        assert scorer._normalize(100, 0, 100) == 100.0
        assert scorer._normalize(50, 0, 100) == 50.0

    def test_normalize_inverse(self, scorer):
        """Inverse normalization: value at min=100, max=0."""
        assert scorer._normalize(0, 0, 100, inverse=True) == 100.0
        assert scorer._normalize(100, 0, 100, inverse=True) == 0.0
        assert scorer._normalize(50, 0, 100, inverse=True) == 50.0

    def test_normalize_equal_values(self, scorer):
        """When min==max, all values should get 50 (midpoint)."""
        assert scorer._normalize(5, 5, 5) == 50.0

    def test_normalize_clamped(self, scorer):
        """Values outside range should be clamped to [0, 100]."""
        result = scorer._normalize(150, 0, 100)
        assert 0 <= result <= 100


class TestScoring:
    """Tests for full scoring pipeline."""

    def test_scores_all_stocks(self, scorer, three_stock_metrics):
        """All stocks should receive scores."""
        scores = scorer.score_stocks(three_stock_metrics)
        assert len(scores) == 3

    def test_score_ranges(self, scorer, three_stock_metrics):
        """Category scores should be in [0, 100]."""
        scores = scorer.score_stocks(three_stock_metrics)
        for score in scores:
            assert 0 <= score.movement_score <= 100
            assert 0 <= score.volatility_score <= 100
            assert 0 <= score.liquidity_score <= 100
            assert 0 <= score.consistency_score <= 100
            assert 0 <= score.risk_penalty <= 100

    def test_stock_a_higher_movement(self, scorer, three_stock_metrics):
        """Stock A (high movement) should have higher movement score than Stock B."""
        scores = scorer.score_stocks(three_stock_metrics)
        score_a = next(s for s in scores if s.symbol == "STOCK_A")
        score_b = next(s for s in scores if s.symbol == "STOCK_B")
        assert score_a.movement_score > score_b.movement_score

    def test_stock_b_higher_liquidity(self, scorer, three_stock_metrics):
        """Stock B (highest volume) should have higher liquidity score."""
        scores = scorer.score_stocks(three_stock_metrics)
        score_b = next(s for s in scores if s.symbol == "STOCK_B")
        score_c = next(s for s in scores if s.symbol == "STOCK_C")
        # Stock B has ~8M volume vs Stock C ~3M
        assert score_b.liquidity_score > score_c.liquidity_score

    def test_explanations_generated(self, scorer, three_stock_metrics):
        """All scores should have non-empty explanations."""
        scores = scorer.score_stocks(three_stock_metrics)
        for score in scores:
            assert score.explanation
            assert len(score.explanation) > 10

    def test_explanations_no_predictions(self, scorer, three_stock_metrics):
        """Explanations must not contain prediction language."""
        scores = scorer.score_stocks(three_stock_metrics)
        forbidden = ["will rise", "guaranteed", "profit", "definitely", "100%"]
        for score in scores:
            for word in forbidden:
                assert word.lower() not in score.explanation.lower(), \
                    f"Explanation contains forbidden word: '{word}'"


class TestSingleStock:
    """Tests for single-stock edge case."""

    def test_single_stock_scores(self, scorer, sample_stock_a):
        """Single stock should get midpoint scores (50)."""
        metrics = calculate_metrics("SOLO", sample_stock_a)
        scores = scorer.score_stocks([metrics])
        assert len(scores) == 1
        assert scores[0].final_score == 50.0


class TestEmptyInput:
    """Tests for empty input."""

    def test_empty_list(self, scorer):
        """Empty list should return empty list."""
        scores = scorer.score_stocks([])
        assert scores == []
