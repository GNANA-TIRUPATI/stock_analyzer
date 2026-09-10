# Indian Day-Trading Stock Analyzer

🇮🇳 A production-quality Python application that automatically collects NSE India historical stock market data and analyzes the previous 15–30 trading days to identify and rank the **Top 5 stocks** that showed the strongest historical characteristics for day trading.

> **⚠️ IMPORTANT DISCLAIMER:** This is a **historical analysis tool**, NOT a prediction system. It does NOT predict future stock performance, guarantee profits, or constitute financial advice. All rankings are based strictly on measurable historical data.

---

## Features

- **Automatic Data Collection**: Fetches historical OHLCV data from NSE India via Yahoo Finance
- **Comprehensive Validation**: 10+ data quality checks before analysis
- **Transparent Scoring**: Reproducible 5-category scoring model with configurable weights
- **Top 5 Ranking**: Deterministic ranking with clear explanations
- **Professional Web Dashboard**: Modern responsive UI with live progress, celebratory animations, and dynamic data exploration
- **Adaptive Dark & Light Mode**: Instant theme switch button (☀️/🌙) with automatic system OS preference detection (`prefers-color-scheme`) and persistent storage
- **Interactive Matrix Chart**: Visual Intraday Trading Profiles Matrix powered by Chart.js with dynamic theme reactivity
- **CLI Mode**: Full analysis without web server
- **Export**: CSV and HTML report generation
- **Extensible**: Modular architecture, abstract provider interface

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- pip

### 2. Installation

```bash
# Clone / navigate to the project
cd "stock analyzer"

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy environment template
copy .env.example .env

# Edit .env if needed (defaults work out of the box)
```

No API key is required for the default data provider (yfinance).

### 4. Run

**Web Dashboard (recommended):**
```bash
python -m app.main
```
Then open http://127.0.0.1:5000 in your browser.

**CLI Mode:**
```bash
python -m app.main --cli
```

---

## Architecture

```
stock-analyzer/
├── app/
│   ├── main.py                 # Entry point (web + CLI)
│   ├── config/
│   │   ├── settings.py         # Environment-based configuration
│   │   └── scoring_weights.yaml # Configurable scoring weights
│   ├── data/
│   │   ├── provider.py         # Abstract data provider interface
│   │   ├── yfinance_provider.py # Yahoo Finance implementation
│   │   ├── universe.py         # Stock universe management
│   │   ├── fetcher.py          # Data retrieval orchestration
│   │   └── validator.py        # Data quality validation
│   ├── analysis/
│   │   ├── metrics.py          # Metric calculations (15 metrics)
│   │   ├── scoring.py          # Normalization & scoring
│   │   └── ranking.py          # Final Top 5 ranking
│   ├── models/
│   │   └── stock_data.py       # Pydantic data models
│   ├── reports/
│   │   └── generator.py        # CSV + HTML report generation
│   └── ui/
│       └── dashboard.py        # Flask web dashboard
├── tests/                      # Automated test suite
├── docs/                       # Technical documentation
├── requirements.txt
├── .env.example
└── README.md
```

### Data Flow

```
Stock Universe → Data Fetcher → Validator → Metrics Calculator → Scorer → Ranker → UI/Report
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATA_PROVIDER` | `yfinance` | Data provider (`yfinance`) |
| `STOCK_UNIVERSE` | `NIFTY_200` | `NIFTY_50`, `NIFTY_100`, `NIFTY_200`, `NIFTY_500` |
| `DEFAULT_ANALYSIS_PERIOD` | `30` | Default trading days: `15` or `30` |
| `FLASK_HOST` | `127.0.0.1` | Web server host |
| `FLASK_PORT` | `5000` | Web server port |
| `FLASK_DEBUG` | `true` | Debug mode |
| `FLASK_SECRET_KEY` | `dev-secret-*` | Flask secret key (change in production) |
| `MAX_REQUESTS_PER_SECOND` | `2` | API rate limit |
| `REQUEST_TIMEOUT` | `30` | Request timeout (seconds) |

---

## Data Provider

### Yahoo Finance (yfinance) — Default

- **Type**: Unofficial wrapper
- **Data**: Daily OHLCV for NSE stocks (`.NS` suffix)
- **Cost**: Free
- **Auth**: None required
- **License**: Apache 2.0 (library); Yahoo Finance Terms of Service (data)
- **Limitations**:
  - Unofficial; Yahoo may change API without notice
  - May be rate-limited with aggressive requests
  - Not guaranteed for commercial redistribution

> The application is designed with a provider abstraction layer. New providers (e.g., Zerodha Kite Connect) can be added by implementing the `BaseDataProvider` interface.

---

## Scoring Methodology (v1.0)

### Score Formula

```
Final Score = (Movement × 0.30) + (Volatility × 0.20) + (Liquidity × 0.25)
            + (Consistency × 0.15) - (Risk Penalty × 0.10)
```

### Categories

| Category | Weight | Metrics |
|---|---|---|
| **Movement** | 30% | Avg HL range %, Avg OC move %, Median HL range % |
| **Volatility** | 20% | Normalized ATR, Daily return std dev |
| **Liquidity** | 25% | Avg volume, Volume consistency, Volume trend |
| **Consistency** | 15% | Movement frequency, Consecutive active days |
| **Risk Penalty** | -10% | Max adverse move, Downside deviation, Gap risk |

### Normalization

Min-max normalization to [0, 100] across all eligible stocks:
- Normal: `(value - min) / (max - min) × 100`
- Inverse (lower is better): `(1 - (value - min) / (max - min)) × 100`

All weights are configurable via `app/config/scoring_weights.yaml`.

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run specific test module
pytest tests/test_metrics.py -v
```

Tests use deterministic sample data with known properties — no live API required.

---

## Known Limitations

1. **Unofficial data source**: yfinance is not officially sanctioned by Yahoo or NSE
2. **Daily data only**: Analysis uses daily OHLCV bars (not intraday candles)
3. **Stock universe**: Based on NIFTY index constituents which are rebalanced semi-annually
4. **No real-time data**: Analysis uses end-of-day historical data
5. **Corporate actions**: Stock splits and bonus issues may cause price discontinuities
6. **Weekend/Holiday detection**: Uses weekday heuristic, not official NSE holiday calendar

---

## Data Licensing

- **yfinance**: Data sourced from Yahoo Finance. Usage subject to Yahoo's Terms of Service.
- **NSE India**: Stock universe data from niftystocks library (NSE index constituents).
- This application is intended for educational and research purposes.
- Verify compliance with data provider terms before commercial use.

---

## Deployment

### Local Development (Default)
```bash
python -m app.main
```

### Production Considerations
- Set `FLASK_DEBUG=false`
- Generate a strong `FLASK_SECRET_KEY`
- Use a production WSGI server (e.g., gunicorn):
  ```bash
  pip install gunicorn
  gunicorn "app.ui.dashboard:create_app()" -b 0.0.0.0:5000
  ```
- Consider adding HTTPS via a reverse proxy (nginx)

---

## License

This project is for educational and research purposes. Ensure compliance with all data provider terms of service before any commercial use.
