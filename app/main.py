"""
Indian Day-Trading Stock Analyzer — Main Entry Point

This application automatically:
    1. Fetches historical NSE India market data
    2. Validates the data quality
    3. Calculates day-trading analysis metrics
    4. Ranks stocks using a transparent scoring model
    5. Displays the Top 5 stocks via a web dashboard

IMPORTANT: This is a HISTORICAL ANALYSIS tool.
    - It does NOT predict future stock performance.
    - It does NOT guarantee profits.
    - Rankings reflect past characteristics only.

Usage:
    python -m app.main          # Start the web dashboard
    python -m app.main --cli    # Run analysis in CLI mode (no web server)

Environment:
    See .env.example for configuration options.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output encoding for Windows consoles/subprocesses
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is on path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def setup_logging():
    """Configure application logging."""
    log_format = (
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)


def run_web_dashboard():
    """Start the Flask web dashboard."""
    from app.config.settings import get_settings
    from app.ui.dashboard import create_app

    settings = get_settings()
    app = create_app()

    print("\n" + "=" * 60)
    print("  🇮🇳 Indian Day-Trading Stock Analyzer")
    print("  Historical Analysis Dashboard")
    print("=" * 60)
    print(f"\n  🌐 Open in browser: http://{settings.flask_host}:{settings.flask_port}")
    print(f"  📊 Data provider: yfinance (Yahoo Finance)")
    print(f"  🔧 Debug mode: {settings.flask_debug}")
    print("\n  ⚠️  DISCLAIMER: Historical analysis only.")
    print("     Not financial advice. No profit guarantees.")
    print("=" * 60 + "\n")

    app.run(
        host=settings.flask_host,
        port=settings.flask_port,
        debug=settings.flask_debug,
    )


def run_cli_analysis():
    """Run analysis in CLI mode without web server."""
    from app.analysis.ranking import rank_stocks
    from app.config.settings import get_settings
    from app.data.fetcher import fetch_all_stocks
    from app.models.stock_data import StockUniverse
    from app.reports.generator import save_report

    settings = get_settings()

    print("\n" + "=" * 60)
    print("  🇮🇳 Indian Day-Trading Stock Analyzer (CLI Mode)")
    print("=" * 60)
    print(f"\n  Analysis period: {settings.default_analysis_period} trading days")
    print(f"  Stock universe: {settings.stock_universe}")
    print(f"  Data provider: yfinance (Yahoo Finance)")
    print("\n  ⚠️  DISCLAIMER: Historical analysis only.\n")

    # Fetch data
    universe = StockUniverse(settings.stock_universe)
    print("  📡 Fetching market data...\n")

    def progress(current, total, symbol):
        pct = current / total * 100 if total > 0 else 0
        print(f"\r  [{pct:5.1f}%] {current}/{total} — {symbol:<15}", end="", flush=True)

    fetch_result = fetch_all_stocks(
        analysis_period=settings.default_analysis_period,
        universe=universe,
        progress_callback=progress,
    )
    print("\n")

    if fetch_result.total_valid == 0:
        print("  ❌ Unable to retrieve sufficient market data.")
        print("     Analysis was not completed.")
        sys.exit(1)

    # Analyze and rank
    print("  🔬 Analyzing metrics and scoring...")
    result = rank_stocks(
        fetch_result,
        analysis_period=settings.default_analysis_period,
        stock_universe=settings.stock_universe,
    )

    # Display results
    print(f"\n  📊 Analysis Summary:")
    print(f"     Period: {result.analysis_start_date} to {result.analysis_end_date}")
    print(f"     Trading days: {result.analysis_period_days}")
    print(f"     Stocks analyzed: {result.total_stocks_analyzed}")
    print(f"     Stocks excluded: {result.total_stocks_excluded}")
    print(f"     Methodology: v{result.scoring_methodology_version}")
    print()

    if result.top_stocks:
        print("  🏆 Top 5 Stocks (Historical Day-Trading Characteristics):")
        print("  " + "-" * 76)
        print(f"  {'Rank':<6} {'Symbol':<12} {'Score':<8} {'Avg Range%':<12} {'Avg Volume':<14} {'Consistency'}")
        print("  " + "-" * 76)

        for ranked in result.top_stocks:
            s = ranked.score
            m = s.metrics
            print(
                f"  #{ranked.rank:<5} {s.symbol:<12} {s.final_score:<8.2f} "
                f"{m.avg_hl_range_pct:<12.2f} {m.avg_volume:<14,.0f} "
                f"{m.movement_frequency:.0%}"
            )

        print("  " + "-" * 76)
        print()

        for ranked in result.top_stocks:
            print(f"  #{ranked.rank} {ranked.score.symbol}:")
            print(f"     {ranked.score.explanation}")
            print()
    else:
        print("  ❌ No stocks could be ranked. Insufficient valid data.")

    # Export reports
    csv_path = save_report(result, format="csv")
    html_path = save_report(result, format="html")
    print(f"  📄 Reports saved:")
    print(f"     CSV: {csv_path}")
    print(f"     HTML: {html_path}")
    print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Indian Day-Trading Stock Analyzer"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode (no web server)",
    )
    args = parser.parse_args()

    setup_logging()

    if args.cli:
        run_cli_analysis()
    else:
        run_web_dashboard()


if __name__ == "__main__":
    main()
