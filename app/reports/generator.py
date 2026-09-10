"""
Report generation module.

Generates exportable reports in CSV and HTML formats.
Each report includes analysis timestamp and methodology version.

IMPORTANT: Reports contain historical analysis only.
No predictions or profit guarantees are included.
"""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Template

from app.models.stock_data import AnalysisResult

logger = logging.getLogger(__name__)

# HTML report template
HTML_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Indian Day-Trading Stock Analysis Report</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0f172a; color: #e2e8f0; padding: 2rem;
            line-height: 1.6;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { font-size: 1.75rem; color: #38bdf8; margin-bottom: 0.5rem; }
        h2 { font-size: 1.25rem; color: #94a3b8; margin: 1.5rem 0 0.75rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.5rem; }
        .disclaimer {
            background: #1e293b; border-left: 4px solid #f59e0b;
            padding: 1rem; margin: 1rem 0; border-radius: 0 0.5rem 0.5rem 0;
            font-size: 0.85rem; color: #fbbf24;
        }
        .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin: 1rem 0; }
        .meta-item { background: #1e293b; padding: 0.75rem; border-radius: 0.5rem; }
        .meta-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; }
        .meta-value { font-size: 0.95rem; color: #e2e8f0; }
        table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
        th { background: #1e293b; color: #94a3b8; padding: 0.75rem; text-align: left; font-size: 0.8rem; text-transform: uppercase; }
        td { padding: 0.75rem; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }
        tr:hover td { background: #1e293b; }
        .rank-1 td:first-child { color: #fbbf24; font-weight: bold; }
        .rank-2 td:first-child { color: #94a3b8; font-weight: bold; }
        .rank-3 td:first-child { color: #cd7f32; font-weight: bold; }
        .explanation { font-size: 0.85rem; color: #94a3b8; padding: 0.5rem 0.75rem; background: #0f172a; }
        .footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #1e293b; font-size: 0.75rem; color: #475569; }
    </style>
</head>
<body>
<div class="container">
    <h1>🇮🇳 Indian Day-Trading Stock Analysis Report</h1>
    <p style="color: #64748b; font-size: 0.9rem;">Generated: {{ report_timestamp }}</p>

    <div class="disclaimer">
        ⚠️ <strong>DISCLAIMER:</strong> This report is a historical analysis of stock market data.
        It does NOT predict future performance, guarantee profits, or constitute financial advice.
        All rankings are based strictly on measurable historical data during the analysis period.
    </div>

    <h2>Analysis Summary</h2>
    <div class="meta">
        <div class="meta-item">
            <div class="meta-label">Analysis Period</div>
            <div class="meta-value">{{ result.analysis_period_days }} trading days ({{ result.analysis_start_date }} to {{ result.analysis_end_date }})</div>
        </div>
        <div class="meta-item">
            <div class="meta-label">Stock Universe</div>
            <div class="meta-value">{{ result.stock_universe }}</div>
        </div>
        <div class="meta-item">
            <div class="meta-label">Stocks Analyzed</div>
            <div class="meta-value">{{ result.total_stocks_analyzed }} of {{ result.total_stocks_in_universe }} ({{ result.total_stocks_excluded }} excluded)</div>
        </div>
        <div class="meta-item">
            <div class="meta-label">Data Provider</div>
            <div class="meta-value">{{ result.data_provider }}</div>
        </div>
        <div class="meta-item">
            <div class="meta-label">Data Retrieved</div>
            <div class="meta-value">{{ result.data_retrieval_timestamp.strftime('%Y-%m-%d %H:%M IST') }}</div>
        </div>
        <div class="meta-item">
            <div class="meta-label">Methodology Version</div>
            <div class="meta-value">v{{ result.scoring_methodology_version }}</div>
        </div>
    </div>

    <h2>Top {{ result.top_stocks|length }} Ranked Stocks</h2>
    {% if result.top_stocks %}
    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Symbol</th>
                <th>Score</th>
                <th>Avg Range %</th>
                <th>Avg Volume</th>
                <th>Volatility</th>
                <th>Consistency</th>
            </tr>
        </thead>
        <tbody>
        {% for ranked in result.top_stocks %}
            <tr class="rank-{{ ranked.rank }}">
                <td>#{{ ranked.rank }}</td>
                <td><strong>{{ ranked.score.symbol }}</strong></td>
                <td>{{ "%.2f"|format(ranked.score.final_score) }}</td>
                <td>{{ "%.2f"|format(ranked.score.metrics.avg_hl_range_pct) }}%</td>
                <td>{{ "{:,.0f}".format(ranked.score.metrics.avg_volume) }}</td>
                <td>{{ "%.4f"|format(ranked.score.metrics.daily_return_std) }}</td>
                <td>{{ "%.0f"|format(ranked.score.metrics.movement_frequency * 100) }}%</td>
            </tr>
            <tr>
                <td colspan="7" class="explanation">{{ ranked.score.explanation }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p style="color: #f87171;">No stocks could be ranked. Insufficient valid data.</p>
    {% endif %}

    {% if result.data_quality_warnings %}
    <h2>Data Quality Warnings ({{ result.data_quality_warnings|length }})</h2>
    <table>
        <thead>
            <tr><th>Symbol</th><th>Type</th><th>Message</th><th>Severity</th></tr>
        </thead>
        <tbody>
        {% for w in result.data_quality_warnings[:20] %}
            <tr>
                <td>{{ w.symbol }}</td>
                <td>{{ w.warning_type }}</td>
                <td>{{ w.message }}</td>
                <td>{{ w.severity }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% if result.data_quality_warnings|length > 20 %}
    <p style="color: #94a3b8; font-size: 0.85rem;">... and {{ result.data_quality_warnings|length - 20 }} more warnings</p>
    {% endif %}
    {% endif %}

    <div class="footer">
        <p>Report generated by Indian Day-Trading Stock Analyzer v{{ result.scoring_methodology_version }}</p>
        <p>This is a historical analysis tool. Past characteristics do not guarantee future results.</p>
    </div>
</div>
</body>
</html>
"""


def generate_csv_report(result: AnalysisResult) -> str:
    """
    Generate CSV report of analysis results.

    Returns CSV content as a string.
    Includes metadata header and all ranked stocks with metrics.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Metadata header
    writer.writerow(["# Indian Day-Trading Stock Analysis Report"])
    writer.writerow(["# Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")])
    writer.writerow(["# Analysis Period", f"{result.analysis_period_days} trading days"])
    writer.writerow(["# Date Range", f"{result.analysis_start_date} to {result.analysis_end_date}"])
    writer.writerow(["# Universe", result.stock_universe])
    writer.writerow(["# Stocks Analyzed", result.total_stocks_analyzed])
    writer.writerow(["# Stocks Excluded", result.total_stocks_excluded])
    writer.writerow(["# Data Provider", result.data_provider])
    writer.writerow(["# Methodology Version", result.scoring_methodology_version])
    writer.writerow(["# DISCLAIMER: Historical analysis only. Not a prediction."])
    writer.writerow([])

    # Column headers
    writer.writerow([
        "Rank", "Symbol", "Final Score",
        "Movement Score", "Volatility Score", "Liquidity Score",
        "Consistency Score", "Risk Penalty",
        "Avg HL Range %", "Avg OC Move %", "Median HL Range %",
        "Daily Return Std", "Normalized ATR %",
        "Avg Volume", "Volume CV", "Relative Volume Trend",
        "Movement Frequency", "Max Consecutive Active Days",
        "Max Adverse Move", "Downside Deviation", "Gap Risk",
        "Trading Days Analyzed", "Avg Close Price",
        "Explanation",
    ])

    # Data rows
    for ranked in result.top_stocks:
        s = ranked.score
        m = s.metrics
        writer.writerow([
            ranked.rank, s.symbol, f"{s.final_score:.2f}",
            f"{s.movement_score:.2f}", f"{s.volatility_score:.2f}",
            f"{s.liquidity_score:.2f}", f"{s.consistency_score:.2f}",
            f"{s.risk_penalty:.2f}",
            f"{m.avg_hl_range_pct:.4f}", f"{m.avg_oc_move_pct:.4f}",
            f"{m.median_hl_range_pct:.4f}",
            f"{m.daily_return_std:.6f}", f"{m.normalized_atr:.4f}",
            f"{m.avg_volume:.0f}", f"{m.volume_cv:.4f}",
            f"{m.relative_volume_trend:.4f}",
            f"{m.movement_frequency:.4f}", m.max_consecutive_active_days,
            f"{m.max_adverse_move:.6f}", f"{m.downside_deviation:.6f}",
            f"{m.gap_risk:.4f}",
            m.trading_days_analyzed, f"{m.avg_close_price:.2f}",
            s.explanation,
        ])

    return output.getvalue()


def generate_html_report(result: AnalysisResult) -> str:
    """
    Generate HTML report of analysis results.

    Returns complete HTML document as a string.
    """
    template = Template(HTML_REPORT_TEMPLATE)
    return template.render(
        result=result,
        report_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
    )


def save_report(
    result: AnalysisResult,
    format: str = "csv",
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Save report to file.

    Args:
        result: Analysis result to report
        format: "csv" or "html"
        output_dir: Directory to save to (default: reports_output/)

    Returns:
        Path to saved report file
    """
    if output_dir is None:
        output_dir = Path("reports_output")

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        content = generate_csv_report(result)
        filename = f"analysis_report_{timestamp}.csv"
    elif format == "html":
        content = generate_html_report(result)
        filename = f"analysis_report_{timestamp}.html"
    else:
        raise ValueError(f"Unsupported format: {format}")

    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Report saved to {filepath}")
    return filepath
