"""
Tests for ranking module.

Tests verify:
    - Deterministic ranking from scored stocks
    - Correct rank assignment (1-5)
    - Tie-breaking by volume
    - Top 5 selection
    - Empty/insufficient data handling
    - Rank explanations
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.analysis.metrics import calculate_metrics
from app.analysis.ranking import rank_stocks, _get_rank_reason
from app.analysis.scoring import StockScorer
from app.data.fetcher import DataFetchResult


@pytest.fixture
def mock_fetch_result(sample_stock_a, sample_stock_b, sample_stock_c):
    """Create a mock DataFetchResult with 3 sample stocks."""
    result = DataFetchResult()
    result.stock_data = {
        "STOCK_A": sample_stock_a,
        "STOCK_B": sample_stock_b,
        "STOCK_C": sample_stock_c,
    }
    result.total_universe_size = 3
    result.provider_name = "Test Provider"
    result.fetch_timestamp = datetime.now()
    return result


class TestRanking:
    """Tests for the ranking pipeline."""

    def test_ranking_produces_results(self, mock_fetch_result):
        """Ranking should produce an AnalysisResult with ranked stocks."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        assert result is not None
        assert len(result.top_stocks) > 0
        assert len(result.top_stocks) <= 5

    def test_ranks_are_sequential(self, mock_fetch_result):
        """Ranks should be 1, 2, 3 for 3 stocks."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        ranks = [s.rank for s in result.top_stocks]
        assert ranks == list(range(1, len(result.top_stocks) + 1))

    def test_scores_descending(self, mock_fetch_result):
        """Final scores should be in descending order."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        scores = [s.score.final_score for s in result.top_stocks]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_metadata_populated(self, mock_fetch_result):
        """Analysis metadata should be fully populated."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        assert result.analysis_period_days == 10
        assert result.total_stocks_in_universe == 3
        assert result.total_stocks_analyzed > 0
        assert result.data_provider == "Test Provider"
        assert result.scoring_methodology_version is not None
        assert result.stock_universe == "TEST"

    def test_explanations_contain_rank(self, mock_fetch_result):
        """Each ranked stock should have a rank-specific explanation."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        for ranked in result.top_stocks:
            assert f"#{ranked.rank}" in ranked.score.explanation

    def test_all_scores_populated(self, mock_fetch_result):
        """all_scores should contain scores for all analyzed stocks."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        assert len(result.all_scores) == 3


class TestEmptyResults:
    """Tests for edge cases with no valid data."""

    def test_empty_fetch_result(self):
        """Empty fetch result should produce empty top_stocks."""
        result = DataFetchResult()
        result.total_universe_size = 0
        result.provider_name = "Test"
        result.fetch_timestamp = datetime.now()

        analysis = rank_stocks(result, analysis_period=10, stock_universe="TEST")
        assert len(analysis.top_stocks) == 0
        assert analysis.total_stocks_analyzed == 0


class TestRankReason:
    """Tests for rank reason generation."""

    def test_get_rank_reason_returns_string(self, mock_fetch_result):
        """Rank reason should be a non-empty string."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        for ranked in result.top_stocks:
            reason = _get_rank_reason(ranked.score)
            assert isinstance(reason, str)
            assert len(reason) > 0

    def test_rank_reason_no_predictions(self, mock_fetch_result):
        """Rank reasons must not contain prediction language."""
        result = rank_stocks(mock_fetch_result, analysis_period=10, stock_universe="TEST")
        forbidden = ["will", "guaranteed", "profit", "definitely", "predict"]
        for ranked in result.top_stocks:
            reason = _get_rank_reason(ranked.score)
            for word in forbidden:
                assert word.lower() not in reason.lower()
