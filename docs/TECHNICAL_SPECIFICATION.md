# Technical Specification — Indian Day-Trading Stock Analyzer

## Version: 1.0

## 1. System Overview

### Purpose
Automatically collect, validate, and analyze NSE India historical stock market data over 15–30 trading days to identify and rank the Top 5 stocks with the strongest historical day-trading characteristics.

### Scope
- **Market**: NSE India only (no US, crypto, forex, or foreign exchanges)
- **Analysis type**: Historical analysis (NOT prediction)
- **Data granularity**: Daily OHLCV (Open, High, Low, Close, Volume)
- **Output**: Top 5 ranked stocks with transparent scoring

## 2. Data Layer

### 2.1 Primary Data Provider: yfinance
- **Type**: Unofficial Python wrapper for Yahoo Finance
- **NSE convention**: `.NS` suffix (e.g., `RELIANCE.NS`)
- **Data interval**: Daily (`1d`)
- **Rate limiting**: Self-throttled at 2 requests/second with exponential backoff
- **Retry policy**: 2 retries per symbol with backoff
- **Error handling**: Graceful degradation — failed symbols are excluded, not fabricated

### 2.2 Stock Universe: niftystocks
- **Source**: `niftystocks` Python library (PyPI)
- **API**: `from niftystocks import ns; ns.get_nifty200()`
- **Options**: NIFTY 50/100/200/500
- **Fallback**: Hardcoded NIFTY 50 list if library unavailable
- **Exclusions**: ETFs, indices, derivatives filtered via configurable exclusion set

### 2.3 Data Validation (10 checks)
1. Empty/null data → exclude stock
2. Missing required columns → exclude stock
3. Duplicate timestamps → keep first, log warning
4. Zero/negative prices → remove rows
5. High < Low → remove rows
6. Open/Close outside [Low, High] → warning only
7. Zero volume → warning (exclusion if >20% days)
8. Insufficient sessions (<80% expected) → exclude stock
9. Suspicious gaps (>20% overnight) → warning
10. Stale data (>3 trading days old) → warning

## 3. Analysis Engine

### 3.1 Metrics (15 total)
See `docs/METHODOLOGY.md` for complete formulas.

### 3.2 Scoring Model
- 5 categories: Movement (30%), Volatility (20%), Liquidity (25%), Consistency (15%), Risk (-10%)
- Min-max normalization to [0, 100]
- All weights configurable via `scoring_weights.yaml`

### 3.3 Ranking
- Sort by final_score descending
- Tie-breaking: higher avg_volume wins
- Select Top 5

## 4. Architecture

### 4.1 Technology Stack
- Python 3.10+
- pandas, numpy (data processing)
- pydantic v2 (data validation)
- Flask (web server)
- Plotly (charts)
- pytest (testing)

### 4.2 Module Separation
- `data/` — acquisition + validation (no analysis logic)
- `analysis/` — metrics + scoring + ranking (no data fetching)
- `ui/` — presentation only (no business logic)
- `models/` — shared data structures
- `config/` — all configuration
- `reports/` — export generation

## 5. Security
- No API keys hard-coded
- `.env` for secrets (gitignored)
- HTTPS-compatible providers
- Input validation on all user controls
- No frontend API key exposure

## 6. Known Limitations
1. yfinance is unofficial
2. Daily data only (not intraday candles)
3. Weekend/holiday detection is heuristic-based
4. Stock universe may lag NSE rebalancing by up to 6 months
5. Corporate actions (splits, bonuses) can cause price discontinuities
6. No real-time data support
