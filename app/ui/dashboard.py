"""
Flask web dashboard for the Indian Day-Trading Stock Analyzer.

Provides a professional, modern UI with:
    - Analysis period selector (15 / 30 trading days)
    - Universe selector
    - Run Analysis button
    - Top 5 results table
    - Detailed metrics display
    - Methodology section
    - Data quality warnings
    - Export controls (CSV / HTML)

IMPORTANT: This is a historical analysis dashboard.
It does NOT predict future stock performance.
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    request,
    send_file,
)

from app.analysis.ranking import rank_stocks
from app.config.settings import get_settings
from app.data.fetcher import DataFetchResult, create_provider, fetch_all_stocks
from app.models.stock_data import AnalysisResult, StockUniverse
from app.reports.generator import generate_csv_report, generate_html_report, save_report

logger = logging.getLogger(__name__)

# Global state for analysis results and progress
_current_result: AnalysisResult = None
_analysis_in_progress = False
_analysis_progress = {"current": 0, "total": 0, "symbol": "", "status": "idle"}


def create_app() -> Flask:
    """Create and configure the Flask application."""
    settings = get_settings()

    app = Flask(
        __name__,
        static_folder=str(Path(__file__).parent / "static"),
        template_folder=str(Path(__file__).parent / "templates"),
    )
    app.secret_key = settings.flask_secret_key

    # Register routes
    _register_routes(app)

    return app


def _register_routes(app: Flask):
    """Register all Flask routes."""

    @app.route("/")
    def index():
        """Main dashboard page."""
        return render_template_string(
            DASHBOARD_HTML,
            result=_current_result,
            in_progress=_analysis_in_progress,
        )

    @app.route("/api/analyze", methods=["POST"])
    def start_analysis():
        """Start a new analysis run."""
        global _analysis_in_progress, _analysis_progress, _current_result

        if _analysis_in_progress:
            return jsonify({"error": "Analysis already in progress"}), 409

        data = request.get_json() or {}
        period = int(data.get("period", 30))
        universe = data.get("universe", "NIFTY_200")

        if period not in (15, 30):
            return jsonify({"error": "Period must be 15 or 30"}), 400

        try:
            universe_enum = StockUniverse(universe)
        except ValueError:
            return jsonify({"error": f"Invalid universe: {universe}"}), 400

        _analysis_in_progress = True
        _analysis_progress = {"current": 0, "total": 0, "symbol": "", "status": "starting"}

        def run_analysis():
            global _current_result, _analysis_in_progress, _analysis_progress
            try:
                _analysis_progress["status"] = "fetching"

                def progress_cb(current, total, symbol):
                    _analysis_progress["current"] = current
                    _analysis_progress["total"] = total
                    _analysis_progress["symbol"] = symbol

                fetch_result = fetch_all_stocks(
                    analysis_period=period,
                    universe=universe_enum,
                    progress_callback=progress_cb,
                )

                _analysis_progress["status"] = "analyzing"

                if fetch_result.total_valid == 0:
                    _analysis_progress["status"] = "error"
                    _analysis_progress["error"] = (
                        "Unable to retrieve sufficient market data. "
                        "Analysis was not completed."
                    )
                    _analysis_in_progress = False
                    return

                result = rank_stocks(
                    fetch_result,
                    analysis_period=period,
                    stock_universe=universe,
                )
                _current_result = result
                _analysis_progress["status"] = "complete"

            except Exception as e:
                logger.error(f"Analysis failed: {e}", exc_info=True)
                _analysis_progress["status"] = "error"
                _analysis_progress["error"] = str(e)
            finally:
                _analysis_in_progress = False

        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()

        return jsonify({"status": "started"})

    @app.route("/api/progress")
    def get_progress():
        """Get current analysis progress."""
        return jsonify(_analysis_progress)

    @app.route("/api/results")
    def get_results():
        """Get current analysis results as JSON."""
        if _current_result is None:
            return jsonify({"error": "No analysis results available"}), 404

        return jsonify(_result_to_dict(_current_result))

    @app.route("/api/export/<format>")
    def export_report(format):
        """Export analysis results as CSV or HTML."""
        if _current_result is None:
            return jsonify({"error": "No analysis results available"}), 404

        if format == "csv":
            content = generate_csv_report(_current_result)
            return Response(
                content,
                mimetype="text/csv",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=analysis_report_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    )
                },
            )
        elif format == "html":
            content = generate_html_report(_current_result)
            return Response(
                content,
                mimetype="text/html",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=analysis_report_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    )
                },
            )
        else:
            return jsonify({"error": f"Unsupported format: {format}"}), 400


def _result_to_dict(result: AnalysisResult) -> dict:
    """Convert AnalysisResult to JSON-serializable dict."""
    return {
        "top_stocks": [
            {
                "rank": r.rank,
                "symbol": r.score.symbol,
                "final_score": r.score.final_score,
                "movement_score": r.score.movement_score,
                "volatility_score": r.score.volatility_score,
                "liquidity_score": r.score.liquidity_score,
                "consistency_score": r.score.consistency_score,
                "risk_penalty": r.score.risk_penalty,
                "explanation": r.score.explanation,
                "metrics": {
                    "avg_hl_range_pct": r.score.metrics.avg_hl_range_pct,
                    "avg_oc_move_pct": r.score.metrics.avg_oc_move_pct,
                    "median_hl_range_pct": r.score.metrics.median_hl_range_pct,
                    "daily_return_std": r.score.metrics.daily_return_std,
                    "normalized_atr": r.score.metrics.normalized_atr,
                    "avg_volume": r.score.metrics.avg_volume,
                    "volume_cv": r.score.metrics.volume_cv,
                    "movement_frequency": r.score.metrics.movement_frequency,
                    "max_consecutive_active_days": r.score.metrics.max_consecutive_active_days,
                    "max_adverse_move": r.score.metrics.max_adverse_move,
                    "gap_risk": r.score.metrics.gap_risk,
                    "trading_days_analyzed": r.score.metrics.trading_days_analyzed,
                    "avg_close_price": r.score.metrics.avg_close_price,
                },
            }
            for r in result.top_stocks
        ],
        "metadata": {
            "analysis_period_days": result.analysis_period_days,
            "analysis_start_date": str(result.analysis_start_date),
            "analysis_end_date": str(result.analysis_end_date),
            "total_stocks_in_universe": result.total_stocks_in_universe,
            "total_stocks_analyzed": result.total_stocks_analyzed,
            "total_stocks_excluded": result.total_stocks_excluded,
            "data_provider": result.data_provider,
            "data_retrieval_timestamp": result.data_retrieval_timestamp.isoformat(),
            "scoring_methodology_version": result.scoring_methodology_version,
            "stock_universe": result.stock_universe,
        },
        "warnings_count": len(result.data_quality_warnings),
        "excluded_count": len(result.excluded_stocks),
    }


# =============================================================================
# DASHBOARD HTML TEMPLATE
# =============================================================================

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Indian Day-Trading Stock Analyzer</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
    <noscript>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    </noscript>
    <script>
        // Immediately apply theme before DOM renders to prevent flash
        (function() {
            try {
                var stored = localStorage.getItem('stock_analyzer_theme');
                var theme = 'dark'; // fallback
                if (stored === 'dark' || stored === 'light') {
                    theme = stored;
                } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
                    theme = 'light';
                }
                document.documentElement.setAttribute('data-theme', theme);
            } catch(e) {}
        })();
    </script>
    <style>
        /* ===== DESIGN TOKENS (LIGHT & DARK) ===== */
        :root, html[data-theme="light"] {
            --bg-primary: #f4f7fb;
            --bg-secondary: #e2e8f0;
            --bg-card: rgba(255, 255, 255, 0.85);
            --bg-card-solid: #ffffff;
            --bg-card-hover: rgba(255, 255, 255, 0.95);
            --bg-glass: rgba(255, 255, 255, 0.7);
            --glass-bg: rgba(255, 255, 255, 0.7);
            --accent-blue: #2563eb;
            --accent-cyan: #0891b2;
            --accent-green: #059669;
            --accent-emerald: #10b981;
            --accent-amber: #d97706;
            --accent-orange: #ea580c;
            --accent-red: #dc2626;
            --accent-pink: #db2777;
            --accent-purple: #7c3aed;
            --accent-indigo: #4f46e5;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-muted: #94a3b8;
            --border: rgba(15, 23, 42, 0.08);
            --border-hover: rgba(15, 23, 42, 0.16);
            --gold: #d97706;
            --silver: #64748b;
            --bronze: #b45309;
            --gradient-brand: linear-gradient(135deg, #4f46e5 0%, #7c3aed 40%, #9333ea 100%);
            --gradient-accent: linear-gradient(135deg, #0891b2 0%, #2563eb 50%, #7c3aed 100%);
            --gradient-warm: linear-gradient(135deg, #ea580c 0%, #dc2626 100%);
            --gradient-success: linear-gradient(135deg, #10b981 0%, #0891b2 100%);
            --glass-border: 1px solid rgba(15, 23, 42, 0.1);
            --glass-blur: blur(20px);
            --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.06);
            --shadow-md: 0 8px 32px rgba(15, 23, 42, 0.08);
            --shadow-lg: 0 16px 64px rgba(15, 23, 42, 0.12);
            --shadow-glow-blue: 0 0 60px rgba(37, 99, 235, 0.15), 0 0 120px rgba(37, 99, 235, 0.05);
            --shadow-glow-purple: 0 0 60px rgba(124, 58, 237, 0.12);
            --shadow-glow-cyan: 0 0 40px rgba(8, 145, 178, 0.1);
            --radius-sm: 0.5rem;
            --radius-md: 0.875rem;
            --radius-lg: 1.25rem;
            --radius-xl: 1.5rem;
            --transition-fast: 0.15s cubic-bezier(0.4, 0, 0.2, 1);
            --transition-base: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            --transition-slow: 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            --transition-spring: 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);

            /* Light-specific tokens */
            --orb-opacity: 0.32;
            --grid-line-color: rgba(148, 163, 184, 0.04);
            --score-ring-bg: #e2e8f0;
            --card-border-subtle: rgba(15, 23, 42, 0.09);
            --explanation-bg: #f8fafc;
            --explanation-text: #334155;
            --disclaimer-bg: #fffbeb;
            --disclaimer-border: #fcd34d;
            --disclaimer-text: #78350f;
            --disclaimer-strong: #451a03;
            --disclaimer-icon: #b45309;
            --switch-bg: #e2e8f0;
            --switch-border: rgba(15, 23, 42, 0.15);
            --switch-thumb: #ffffff;
            --select-bg: #ffffff;
            --select-border: rgba(15, 23, 42, 0.12);
            --select-arrow: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23475569' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
            --rank1-bg: #fef3c7; --rank1-text: #b45309; --rank1-border: #fcd34d;
            --rank2-bg: #f1f5f9; --rank2-text: #475569; --rank2-border: #cbd5e1;
            --rank3-bg: #ffedd5; --rank3-text: #c2410c; --rank3-border: #fdba74;
            --rank4-bg: #e0e7ff; --rank4-text: #4338ca; --rank4-border: #a5b4fc;
            --pill-movement-bg: linear-gradient(180deg, #ffffff 0%, #eff6ff 100%);
            --pill-movement-border: #bfdbfe;
            --pill-movement-text: #1e40af;
            --pill-movement-val: #1d4ed8;
            --pill-volatility-bg: linear-gradient(180deg, #ffffff 0%, #fffbeb 100%);
            --pill-volatility-border: #fde68a;
            --pill-volatility-text: #92400e;
            --pill-volatility-val: #b45309;
            --pill-liquidity-bg: linear-gradient(180deg, #ffffff 0%, #f0fdf4 100%);
            --pill-liquidity-border: #bbf7d0;
            --pill-liquidity-text: #166534;
            --pill-liquidity-val: #15803d;
            --pill-consistency-bg: linear-gradient(180deg, #ffffff 0%, #faf5ff 100%);
            --pill-consistency-border: #e9d5ff;
            --pill-consistency-text: #6b21a8;
            --pill-consistency-val: #7e22ce;
            --pill-risk-bg: linear-gradient(180deg, #ffffff 0%, #fff1f2 100%);
            --pill-risk-border: #fecdd3;
            --pill-risk-text: #9f1239;
            --pill-risk-val: #be123c;
            --pill-movement-bar-bg: #dbeafe;
            --pill-volatility-bar-bg: #fef3c7;
            --pill-liquidity-bar-bg: #dcfce7;
            --pill-consistency-bar-bg: #f3e8ff;
            --pill-risk-bar-bg: #ffe4e6;
        }

        html[data-theme="dark"] {
            --bg-primary: #0a0e1a;
            --bg-secondary: #141d2e;
            --bg-card: rgba(18, 26, 43, 0.85);
            --bg-card-solid: #111827;
            --bg-card-hover: rgba(28, 39, 64, 0.95);
            --bg-glass: rgba(18, 26, 43, 0.7);
            --glass-bg: rgba(18, 26, 43, 0.7);
            --accent-blue: #3b82f6;
            --accent-cyan: #22d3ee;
            --accent-green: #10b981;
            --accent-emerald: #34d399;
            --accent-amber: #f59e0b;
            --accent-orange: #f97316;
            --accent-red: #ef4444;
            --accent-pink: #f472b6;
            --accent-purple: #8b5cf6;
            --accent-indigo: #6366f1;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.18);
            --glass-border: 1px solid rgba(255, 255, 255, 0.08);
            --glass-blur: blur(20px);
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 8px 32px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 16px 64px rgba(0, 0, 0, 0.5);
            --shadow-glow-blue: 0 0 60px rgba(59, 130, 246, 0.2), 0 0 120px rgba(59, 130, 246, 0.08);
            --shadow-glow-purple: 0 0 60px rgba(139, 92, 246, 0.18);
            --shadow-glow-cyan: 0 0 40px rgba(34, 211, 238, 0.15);

            /* Dark-specific tokens */
            --orb-opacity: 0.45;
            --grid-line-color: rgba(255, 255, 255, 0.03);
            --score-ring-bg: #1e293b;
            --card-border-subtle: rgba(255, 255, 255, 0.08);
            --explanation-bg: rgba(99, 102, 241, 0.09);
            --explanation-text: #cbd5e1;
            --disclaimer-bg: rgba(245, 158, 11, 0.08);
            --disclaimer-border: rgba(245, 158, 11, 0.25);
            --disclaimer-text: #fcd34d;
            --disclaimer-strong: #fef08a;
            --disclaimer-icon: #f59e0b;
            --switch-bg: #1e293b;
            --switch-border: rgba(255, 255, 255, 0.18);
            --switch-thumb: #38bdf8;
            --select-bg: #141d2e;
            --select-border: rgba(255, 255, 255, 0.12);
            --select-arrow: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
            --rank1-bg: rgba(245, 158, 11, 0.15); --rank1-text: #fbbf24; --rank1-border: rgba(245, 158, 11, 0.4);
            --rank2-bg: rgba(148, 163, 184, 0.15); --rank2-text: #cbd5e1; --rank2-border: rgba(148, 163, 184, 0.4);
            --rank3-bg: rgba(234, 88, 12, 0.15); --rank3-text: #fb923c; --rank3-border: rgba(234, 88, 12, 0.4);
            --rank4-bg: rgba(99, 102, 241, 0.15); --rank4-text: #a5b4fc; --rank4-border: rgba(99, 102, 241, 0.4);
            --pill-movement-bg: linear-gradient(180deg, rgba(30, 58, 138, 0.3) 0%, rgba(15, 23, 42, 0.7) 100%);
            --pill-movement-border: rgba(96, 165, 250, 0.25);
            --pill-movement-text: #93c5fd;
            --pill-movement-val: #60a5fa;
            --pill-volatility-bg: linear-gradient(180deg, rgba(146, 64, 14, 0.3) 0%, rgba(15, 23, 42, 0.7) 100%);
            --pill-volatility-border: rgba(251, 191, 36, 0.25);
            --pill-volatility-text: #fde68a;
            --pill-volatility-val: #fbbf24;
            --pill-liquidity-bg: linear-gradient(180deg, rgba(22, 101, 52, 0.3) 0%, rgba(15, 23, 42, 0.7) 100%);
            --pill-liquidity-border: rgba(74, 222, 128, 0.25);
            --pill-liquidity-text: #86efac;
            --pill-liquidity-val: #4ade80;
            --pill-consistency-bg: linear-gradient(180deg, rgba(107, 33, 168, 0.3) 0%, rgba(15, 23, 42, 0.7) 100%);
            --pill-consistency-border: rgba(192, 132, 252, 0.25);
            --pill-consistency-text: #d8b4fe;
            --pill-consistency-val: #c084fc;
            --pill-risk-bg: linear-gradient(180deg, rgba(159, 18, 57, 0.3) 0%, rgba(15, 23, 42, 0.7) 100%);
            --pill-risk-border: rgba(251, 113, 133, 0.25);
            --pill-risk-text: #fda4af;
            --pill-risk-val: #fb7185;
            --pill-movement-bar-bg: rgba(30, 58, 138, 0.4);
            --pill-volatility-bar-bg: rgba(146, 64, 14, 0.4);
            --pill-liquidity-bar-bg: rgba(22, 101, 52, 0.4);
            --pill-consistency-bar-bg: rgba(107, 33, 168, 0.4);
            --pill-risk-bar-bg: rgba(159, 18, 57, 0.4);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        html { scroll-behavior: smooth; }

        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        /* ===== ANIMATED MESH BACKGROUND ===== */
        .bg-mesh {
            position: fixed;
            inset: 0;
            z-index: 0;
            overflow: hidden;
            pointer-events: none;
        }

        .bg-mesh .orb {
            position: absolute;
            border-radius: 50%;
            filter: blur(80px);
            opacity: var(--orb-opacity);
            animation: orbFloat 20s ease-in-out infinite;
            transition: opacity var(--transition-slow);
        }

        .bg-mesh .orb:nth-child(1) {
            width: 600px; height: 600px;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.2) 0%, transparent 70%);
            top: -10%; left: -5%;
            animation-duration: 25s;
        }

        .bg-mesh .orb:nth-child(2) {
            width: 500px; height: 500px;
            background: radial-gradient(circle, rgba(34, 211, 238, 0.15) 0%, transparent 70%);
            top: 40%; right: -10%;
            animation-duration: 30s;
            animation-delay: -5s;
        }

        .bg-mesh .orb:nth-child(3) {
            width: 400px; height: 400px;
            background: radial-gradient(circle, rgba(168, 85, 247, 0.12) 0%, transparent 70%);
            bottom: -5%; left: 30%;
            animation-duration: 22s;
            animation-delay: -10s;
        }

        .bg-mesh .orb:nth-child(4) {
            width: 300px; height: 300px;
            background: radial-gradient(circle, rgba(59, 130, 246, 0.1) 0%, transparent 70%);
            top: 20%; left: 50%;
            animation-duration: 28s;
            animation-delay: -15s;
        }

        @keyframes orbFloat {
            0%, 100% { transform: translate(0, 0) scale(1); }
            25% { transform: translate(40px, -30px) scale(1.05); }
            50% { transform: translate(-20px, 40px) scale(0.95); }
            75% { transform: translate(30px, 20px) scale(1.02); }
        }

        /* Grid overlay */
        .bg-mesh::after {
            content: '';
            position: absolute;
            inset: 0;
            background-image:
                linear-gradient(var(--grid-line-color) 1px, transparent 1px),
                linear-gradient(90deg, var(--grid-line-color) 1px, transparent 1px);
            background-size: 60px 60px;
            mask-image: radial-gradient(ellipse at 50% 30%, black 20%, transparent 70%);
            -webkit-mask-image: radial-gradient(ellipse at 50% 30%, black 20%, transparent 70%);
        }

        /* ===== ENTRANCE ANIMATIONS ===== */
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(24px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-16px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes fadeInScale {
            from { opacity: 0; transform: scale(0.92); }
            to { opacity: 1; transform: scale(1); }
        }

        @keyframes slideInRight {
            from { opacity: 0; transform: translateX(30px); }
            to { opacity: 1; transform: translateX(0); }
        }

        @keyframes shimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }

        @keyframes pulseGlow {
            0%, 100% { box-shadow: 0 0 20px rgba(34, 211, 238, 0.1); }
            50% { box-shadow: 0 0 40px rgba(34, 211, 238, 0.2); }
        }

        @keyframes borderGlow {
            0%, 100% { border-color: rgba(99, 102, 241, 0.2); }
            50% { border-color: rgba(99, 102, 241, 0.4); }
        }

        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-8px); }
        }

        @keyframes countUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes barGrow {
            from { width: 0%; }
        }

        @keyframes celebratePop {
            0% { transform: scale(0); opacity: 0; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(1); opacity: 1; }
        }

        .animate-in {
            opacity: 0;
            animation: fadeInUp 0.6s var(--transition-base) forwards;
        }

        .animate-in-scale {
            opacity: 0;
            animation: fadeInScale 0.5s var(--transition-base) forwards;
        }

        .stagger-1 { animation-delay: 0.05s; }
        .stagger-2 { animation-delay: 0.1s; }
        .stagger-3 { animation-delay: 0.15s; }
        .stagger-4 { animation-delay: 0.2s; }
        .stagger-5 { animation-delay: 0.25s; }
        .stagger-6 { animation-delay: 0.3s; }

        /* ===== LAYOUT ===== */
        .app-container {
            position: relative;
            z-index: 1;
            max-width: 1360px;
            margin: 0 auto;
            padding: 1.25rem 1.5rem;
        }

        /* ===== HEADER ===== */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 0 1.5rem;
            margin-bottom: 1.5rem;
            animation: fadeInDown 0.7s ease forwards;
        }

        .header-left h1 {
            font-size: 1.65rem;
            font-weight: 800;
            background: var(--gradient-accent);
            background-size: 200% auto;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.03em;
            line-height: 1.2;
            animation: shimmer 6s linear infinite;
        }

        .header-left .subtitle {
            font-size: 0.82rem;
            color: var(--text-muted);
            margin-top: 0.35rem;
            font-weight: 400;
            letter-spacing: 0.01em;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .header-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            background: rgba(34, 211, 238, 0.08);
            color: var(--accent-cyan);
            padding: 0.4rem 0.9rem;
            border-radius: 2rem;
            font-size: 0.72rem;
            font-weight: 600;
            border: 1px solid rgba(34, 211, 238, 0.15);
            letter-spacing: 0.02em;
            transition: all var(--transition-base);
            cursor: default;
        }

        .header-badge:hover {
            background: rgba(34, 211, 238, 0.14);
            border-color: rgba(34, 211, 238, 0.3);
            transform: translateY(-1px);
        }

        .header-badge .pulse-dot {
            width: 6px; height: 6px;
            background: var(--accent-cyan);
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(0.8); }
        }

        /* ===== THEME SWITCH ===== */
        .theme-switch-wrapper {
            display: inline-flex;
            align-items: center;
        }

        .theme-toggle-btn {
            position: relative;
            display: inline-flex;
            align-items: center;
            justify-content: space-between;
            width: 66px;
            height: 32px;
            background: var(--switch-bg);
            border: 1px solid var(--switch-border);
            border-radius: 100px;
            padding: 3px 6px;
            cursor: pointer;
            outline: none;
            transition: all var(--transition-base);
            box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.08), var(--shadow-sm);
        }

        .theme-toggle-btn:hover {
            border-color: var(--accent-indigo);
            box-shadow: 0 0 12px rgba(99, 102, 241, 0.25);
            transform: translateY(-1px);
        }

        .theme-toggle-btn:focus-visible {
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.35);
        }

        .theme-icon {
            font-size: 0.85rem;
            line-height: 1;
            z-index: 1;
            transition: opacity var(--transition-base), transform var(--transition-base);
            user-select: none;
        }

        .theme-icon-sun {
            color: #f59e0b;
        }

        .theme-icon-moon {
            color: #38bdf8;
        }

        .theme-thumb {
            position: absolute;
            top: 3px;
            left: 3px;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: var(--bg-card-solid);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
            transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background var(--transition-base);
            z-index: 2;
        }

        html[data-theme="dark"] .theme-thumb {
            transform: translateX(34px);
            background: #1e293b;
        }

        .live-clock {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-primary);
            background: var(--bg-card-solid);
            padding: 0.4rem 0.9rem;
            border-radius: 2rem;
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
            letter-spacing: 0.02em;
            transition: all var(--transition-base);
        }

        /* ===== DISCLAIMER ===== */
        .disclaimer-banner {
            background: var(--disclaimer-bg);
            border: 1px solid var(--disclaimer-border);
            border-radius: var(--radius-md);
            padding: 0.875rem 1.25rem;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            box-shadow: 0 1px 3px rgba(245, 158, 11, 0.08);
            animation: fadeInUp 0.6s ease forwards;
            animation-delay: 0.1s;
            opacity: 0;
            transition: all var(--transition-base);
        }

        .disclaimer-banner:hover {
            border-color: var(--accent-amber);
        }

        .disclaimer-banner .icon { font-size: 1.15rem; color: var(--disclaimer-icon); flex-shrink: 0; margin-top: 0.05rem; }
        .disclaimer-banner .text { font-size: 0.78rem; color: var(--disclaimer-text); line-height: 1.6; font-weight: 500; }
        .disclaimer-banner strong { color: var(--disclaimer-strong); font-weight: 700; }

        /* ===== GLASS CARD BASE ===== */
        .glass-card {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            -webkit-backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            transition: all var(--transition-base);
        }

        .glass-card:hover {
            border-color: var(--border-hover);
        }

        /* ===== CONTROLS ===== */
        .controls-panel {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            padding: 1.25rem 1.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            gap: 1.25rem;
            align-items: flex-end;
            flex-wrap: wrap;
            animation: fadeInUp 0.6s ease forwards;
            animation-delay: 0.15s;
            opacity: 0;
            transition: all var(--transition-base);
        }

        .controls-panel:hover {
            border-color: var(--border-hover);
            box-shadow: var(--shadow-glow-blue);
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }

        .control-group label {
            font-size: 0.68rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
        }

        .control-group select {
            background: var(--select-bg);
            color: var(--text-primary);
            border: 1px solid var(--select-border);
            border-radius: var(--radius-sm);
            padding: 0.625rem 1rem;
            font-size: 0.85rem;
            font-family: inherit;
            font-weight: 500;
            cursor: pointer;
            min-width: 200px;
            transition: all var(--transition-base);
            appearance: none;
            background-image: var(--select-arrow);
            background-repeat: no-repeat;
            background-position: right 0.75rem center;
            padding-right: 2.25rem;
        }

        .control-group select:hover {
            border-color: var(--accent-indigo);
            background-color: var(--bg-card-hover);
        }

        .control-group select:focus {
            outline: none;
            border-color: var(--accent-indigo);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15), 0 0 20px rgba(99, 102, 241, 0.1);
        }

        /* ===== BUTTONS ===== */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.625rem 1.5rem;
            border-radius: var(--radius-sm);
            font-size: 0.85rem;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            border: none;
            transition: all var(--transition-base);
            position: relative;
            overflow: hidden;
        }

        .btn::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, transparent 50%);
            opacity: 0;
            transition: opacity var(--transition-fast);
        }

        .btn:hover::after { opacity: 1; }

        .btn-primary {
            background: var(--gradient-brand);
            color: white;
            box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3), inset 0 1px 0 rgba(255,255,255,0.1);
            letter-spacing: 0.01em;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(99, 102, 241, 0.4), inset 0 1px 0 rgba(255,255,255,0.15);
        }

        .btn-primary:active {
            transform: translateY(0);
            box-shadow: 0 2px 10px rgba(99, 102, 241, 0.3);
        }

        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none;
        }

        .btn-export {
            background: rgba(34, 211, 238, 0.06);
            color: var(--accent-cyan);
            border: 1px solid rgba(34, 211, 238, 0.12);
            padding: 0.45rem 0.875rem;
            font-size: 0.76rem;
            border-radius: var(--radius-sm);
            font-weight: 600;
            letter-spacing: 0.02em;
        }

        .btn-export:hover {
            background: rgba(34, 211, 238, 0.12);
            border-color: rgba(34, 211, 238, 0.25);
            transform: translateY(-1px);
            box-shadow: var(--shadow-glow-cyan);
        }

        /* ===== PROGRESS ===== */
        .progress-panel {
            display: none;
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            animation: fadeInScale 0.4s ease forwards;
        }

        .progress-panel.active { display: block; animation: borderGlow 2s ease-in-out infinite; }

        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.875rem;
        }

        .progress-stage {
            display: flex;
            align-items: center;
            gap: 0.625rem;
        }

        .progress-stage .stage-icon {
            width: 32px; height: 32px;
            border-radius: 50%;
            background: rgba(99, 102, 241, 0.1);
            border: 1.5px solid rgba(99, 102, 241, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.85rem;
            animation: pulse 2s ease-in-out infinite;
        }

        .progress-stage .stage-text {
            font-size: 0.88rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .progress-stage .stage-sub {
            font-size: 0.75rem;
            color: var(--text-muted);
            font-weight: 400;
        }

        .progress-bar-container {
            background: var(--bg-secondary);
            border-radius: 100px;
            height: 10px;
            overflow: hidden;
            margin: 0.875rem 0;
            position: relative;
        }

        .progress-bar {
            height: 100%;
            background: var(--gradient-accent);
            background-size: 200% auto;
            border-radius: 100px;
            transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            width: 0%;
            position: relative;
        }

        .progress-bar::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.25) 50%, transparent 100%);
            background-size: 200% 100%;
            animation: shimmer 1.5s linear infinite;
        }

        .progress-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.78rem;
        }

        .progress-symbol-tag {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            background: rgba(34, 211, 238, 0.08);
            color: var(--accent-cyan);
            padding: 0.25rem 0.65rem;
            border-radius: 2rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            font-weight: 500;
            border: 1px solid rgba(34, 211, 238, 0.1);
        }

        .progress-count {
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-secondary);
            font-weight: 500;
        }

        /* ===== SUMMARY CARDS ===== */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }

        .summary-card {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-md);
            padding: 1.25rem 1.35rem;
            transition: all var(--transition-base);
            position: relative;
            overflow: hidden;
        }

        .summary-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 2px;
            background: var(--gradient-accent);
            opacity: 0;
            transition: opacity var(--transition-base);
        }

        .summary-card:hover {
            border-color: var(--border-hover);
            transform: translateY(-3px);
            box-shadow: var(--shadow-md);
        }

        .summary-card:hover::before { opacity: 1; }

        .summary-card .card-icon {
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
            display: block;
        }

        .summary-card .label {
            font-size: 0.68rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 0.4rem;
        }

        .summary-card .value {
            font-size: 1.65rem;
            font-weight: 800;
            color: var(--text-primary);
            letter-spacing: -0.02em;
            line-height: 1.1;
        }

        .summary-card .detail {
            font-size: 0.76rem;
            color: var(--text-secondary);
            margin-top: 0.35rem;
            font-weight: 400;
        }

        /* ===== TOP 5 RESULTS ===== */
        .results-section {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            overflow: hidden;
            margin-bottom: 1.5rem;
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border);
        }

        .section-title {
            font-size: 1.05rem;
            font-weight: 700;
            letter-spacing: -0.01em;
        }

        .export-buttons { display: flex; gap: 0.5rem; }

        /* Stock Cards (replaces table on all views) */
        .stock-cards-container {
            padding: 1rem 1.25rem;
        }

        .stock-card {
            background: var(--bg-card-solid);
            border: 1px solid var(--card-border-subtle);
            border-radius: var(--radius-md);
            padding: 1.35rem 1.5rem;
            margin-bottom: 1rem;
            box-shadow: var(--shadow-sm);
            transition: all var(--transition-base);
            cursor: default;
            position: relative;
            overflow: hidden;
        }

        .stock-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; bottom: 0;
            width: 4px;
            border-radius: 4px 0 0 4px;
            transition: all var(--transition-base);
        }

        .stock-card.rank-1-card::before { background: #f59e0b; }
        .stock-card.rank-2-card::before { background: #64748b; }
        .stock-card.rank-3-card::before { background: #d97706; }
        .stock-card.rank-4-card::before, .stock-card.rank-5-card::before { background: #6366f1; }

        .stock-card:hover {
            border-color: rgba(99, 102, 241, 0.3);
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }

        .stock-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.1rem;
        }

        .stock-card-left {
            display: flex;
            align-items: center;
            gap: 0.875rem;
        }

        .rank-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 38px;
            border-radius: 10px;
            font-weight: 800;
            font-size: 0.95rem;
            flex-shrink: 0;
            transition: all var(--transition-base);
        }

        .rank-1 { background: var(--rank1-bg); color: var(--rank1-text); border: 1.5px solid var(--rank1-border); }
        .rank-2 { background: var(--rank2-bg); color: var(--rank2-text); border: 1.5px solid var(--rank2-border); }
        .rank-3 { background: var(--rank3-bg); color: var(--rank3-text); border: 1.5px solid var(--rank3-border); }
        .rank-4, .rank-5 { background: var(--rank4-bg); color: var(--rank4-text); border: 1.5px solid var(--rank4-border); }

        .stock-identity .symbol-name {
            font-weight: 800;
            font-size: 1.2rem;
            letter-spacing: -0.02em;
            color: var(--text-primary);
            transition: color var(--transition-base);
        }

        .stock-identity .price-tag {
            font-size: 0.78rem;
            color: var(--text-secondary);
            margin-top: 0.2rem;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            transition: color var(--transition-base);
        }

        .score-ring {
            position: relative;
            width: 58px;
            height: 58px;
            flex-shrink: 0;
        }

        .score-ring svg {
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }

        .score-ring .ring-bg {
            fill: none;
            stroke: var(--score-ring-bg);
            stroke-width: 4;
            transition: stroke var(--transition-base);
        }

        .score-ring .ring-fill {
            fill: none;
            stroke-width: 4;
            stroke-linecap: round;
            transition: stroke-dashoffset 1.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .score-ring .score-text {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 0.9rem;
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-primary);
            transition: color var(--transition-base);
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 0.75rem;
        }

        .metric-pill {
            background: var(--bg-card-solid);
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            padding: 0.75rem 0.85rem;
            box-shadow: var(--shadow-sm);
            transition: all var(--transition-base);
            position: relative;
        }

        .metric-pill:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
            border-color: var(--border-hover);
        }

        .metric-pill.pill-movement {
            background: var(--pill-movement-bg);
            border-color: var(--pill-movement-border);
        }
        .metric-pill.pill-volatility {
            background: var(--pill-volatility-bg);
            border-color: var(--pill-volatility-border);
        }
        .metric-pill.pill-liquidity {
            background: var(--pill-liquidity-bg);
            border-color: var(--pill-liquidity-border);
        }
        .metric-pill.pill-consistency {
            background: var(--pill-consistency-bg);
            border-color: var(--pill-consistency-border);
        }
        .metric-pill.pill-risk {
            background: var(--pill-risk-bg);
            border-color: var(--pill-risk-border);
        }

        .metric-pill .metric-label {
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-bottom: 0.35rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .pill-movement .metric-label { color: var(--pill-movement-text); }
        .pill-volatility .metric-label { color: var(--pill-volatility-text); }
        .pill-liquidity .metric-label { color: var(--pill-liquidity-text); }
        .pill-consistency .metric-label { color: var(--pill-consistency-text); }
        .pill-risk .metric-label { color: var(--pill-risk-text); }

        .metric-pill .metric-value {
            font-size: 1.22rem;
            font-weight: 800;
            font-family: 'JetBrains Mono', monospace;
            line-height: 1.1;
        }
        .pill-movement .metric-value { color: var(--pill-movement-val); }
        .pill-volatility .metric-value { color: var(--pill-volatility-val); }
        .pill-liquidity .metric-value { color: var(--pill-liquidity-val); }
        .pill-consistency .metric-value { color: var(--pill-consistency-val); }
        .pill-risk .metric-value { color: var(--pill-risk-val); }

        .metric-pill .metric-bar-mini {
            height: 5px;
            border-radius: 100px;
            margin-top: 0.55rem;
            overflow: hidden;
        }
        .pill-movement .metric-bar-mini { background: var(--pill-movement-bar-bg); }
        .pill-volatility .metric-bar-mini { background: var(--pill-volatility-bar-bg); }
        .pill-liquidity .metric-bar-mini { background: var(--pill-liquidity-bar-bg); }
        .pill-consistency .metric-bar-mini { background: var(--pill-consistency-bar-bg); }
        .pill-risk .metric-bar-mini { background: var(--pill-risk-bar-bg); }

        .pill-movement .metric-bar-mini-fill { background: linear-gradient(90deg, #3b82f6, #1d4ed8); }
        .pill-volatility .metric-bar-mini-fill { background: linear-gradient(90deg, #f59e0b, #d97706); }
        .pill-liquidity .metric-bar-mini-fill { background: linear-gradient(90deg, #10b981, #059669); }
        .pill-consistency .metric-bar-mini-fill { background: linear-gradient(90deg, #a855f7, #7c3aed); }
        .pill-risk .metric-bar-mini-fill { background: linear-gradient(90deg, #f43f5e, #e11d48); }

        .color-blue { color: #1d4ed8; }
        .color-cyan { color: #0284c7; }
        .color-green { color: #15803d; }
        .color-purple { color: #7e22ce; }
        .color-red { color: #be123c; }

        .bg-blue { background: #2563eb; }
        .bg-cyan { background: #0284c7; }
        .bg-green { background: #059669; }
        .bg-purple { background: #7c3aed; }
        .bg-red { background: #dc2626; }

        .stock-explanation {
            margin-top: 1rem;
            padding: 0.75rem 1rem;
            background: var(--explanation-bg);
            border-left: 3px solid var(--accent-indigo);
            border-radius: 0 0.5rem 0.5rem 0;
            font-size: 0.84rem;
            color: var(--explanation-text);
            font-weight: 500;
            line-height: 1.6;
            transition: all var(--transition-base);
        }

        /* ===== METHODOLOGY ===== */
        .methodology-section {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }

        .methodology-section h3 {
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 1.125rem;
            letter-spacing: -0.01em;
        }

        .method-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 0.75rem;
        }

        .method-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1rem 1.125rem;
            transition: all var(--transition-base);
            position: relative;
        }

        .method-card:hover {
            border-color: var(--border-hover);
            transform: translateY(-2px);
            box-shadow: var(--shadow-sm);
        }

        .method-card h4 {
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .weight-badge {
            background: rgba(99, 102, 241, 0.1);
            color: var(--accent-indigo);
            padding: 0.15rem 0.5rem;
            border-radius: 2rem;
            font-size: 0.65rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.02em;
        }

        .method-card p, .method-card ul {
            font-size: 0.78rem;
            color: var(--text-secondary);
            line-height: 1.55;
        }

        .method-card ul { padding-left: 1rem; }
        .method-card li { margin-bottom: 0.2rem; }

        /* ===== WARNINGS ===== */
        .warnings-section {
            background: var(--bg-card);
            backdrop-filter: var(--glass-blur);
            border: var(--glass-border);
            border-radius: var(--radius-lg);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }

        .warning-item {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.75rem 1rem;
            background: rgba(251, 191, 36, 0.04);
            border: 1px solid rgba(251, 191, 36, 0.08);
            border-radius: var(--radius-sm);
            margin-bottom: 0.5rem;
            font-size: 0.78rem;
            color: var(--text-secondary);
            transition: all var(--transition-fast);
        }

        .warning-item:hover {
            background: rgba(251, 191, 36, 0.07);
            border-color: rgba(251, 191, 36, 0.15);
        }

        .warning-icon { color: var(--accent-amber); font-size: 0.95rem; flex-shrink: 0; }

        /* ===== EMPTY STATE ===== */
        .empty-state {
            text-align: center;
            padding: 5rem 2rem;
            animation: fadeInUp 0.8s ease forwards;
            animation-delay: 0.25s;
            opacity: 0;
        }

        .empty-icon-container {
            width: 80px; height: 80px;
            margin: 0 auto 1.5rem;
            background: rgba(99, 102, 241, 0.06);
            border-radius: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.25rem;
            animation: float 4s ease-in-out infinite;
            border: 1px solid rgba(99, 102, 241, 0.1);
        }

        .empty-state h3 {
            color: var(--text-primary);
            margin-bottom: 0.5rem;
            font-weight: 700;
            font-size: 1.15rem;
            letter-spacing: -0.01em;
        }

        .empty-state p { color: var(--text-secondary); font-size: 0.88rem; max-width: 440px; margin: 0 auto; line-height: 1.6; }

        .empty-steps {
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-top: 2.5rem;
            flex-wrap: wrap;
        }

        .empty-step {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            color: var(--text-muted);
            font-size: 0.78rem;
            font-weight: 500;
        }

        .empty-step .step-num {
            width: 24px; height: 24px;
            border-radius: 50%;
            background: rgba(99, 102, 241, 0.1);
            border: 1px solid rgba(99, 102, 241, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.68rem;
            font-weight: 700;
            color: var(--accent-indigo);
            font-family: 'JetBrains Mono', monospace;
        }

        /* ===== ERROR STATE ===== */
        .error-banner {
            background: rgba(248, 113, 113, 0.06);
            border: 1px solid rgba(248, 113, 113, 0.15);
            border-radius: var(--radius-md);
            padding: 1rem 1.25rem;
            margin-bottom: 1.5rem;
            color: var(--accent-red);
            font-size: 0.85rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            animation: fadeInScale 0.3s ease forwards;
            backdrop-filter: var(--glass-blur);
        }

        /* ===== SPINNER ===== */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.2);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 0.7s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        /* ===== FOOTER ===== */
        .footer {
            text-align: center;
            padding: 2rem 0 1.5rem;
            color: var(--text-muted);
            font-size: 0.72rem;
            border-top: 1px solid var(--border);
            margin-top: 1rem;
        }

        .footer p + p { margin-top: 0.25rem; }

        /* ===== CELEBRATION OVERLAY ===== */
        .confetti-container {
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 9999;
            overflow: hidden;
        }

        .confetti-piece {
            position: absolute;
            width: 8px; height: 8px;
            border-radius: 2px;
            top: -10px;
            animation: confettiFall linear forwards;
        }

        @keyframes confettiFall {
            0% { transform: translateY(0) rotate(0deg) scale(1); opacity: 1; }
            80% { opacity: 1; }
            100% { transform: translateY(100vh) rotate(720deg) scale(0.5); opacity: 0; }
        }

        /* ===== SCROLLBAR ===== */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.15); border-radius: 100px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(148, 163, 184, 0.25); }

        /* ===== RESPONSIVE ===== */
        @media (max-width: 1024px) {
            .metrics-grid {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        @media (max-width: 768px) {
            .app-container { padding: 1rem; }
            .controls-panel { flex-direction: column; align-items: stretch; padding: 1rem; }
            .control-group select { min-width: 100%; }
            .header { flex-direction: column; gap: 0.75rem; align-items: flex-start; }
            .header-right { align-self: flex-start; }
            .section-header { flex-direction: column; gap: 0.75rem; align-items: flex-start; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); }
            .stock-card-header { flex-direction: column; gap: 0.75rem; }
            .score-ring { align-self: flex-end; }
            .empty-steps { flex-direction: column; align-items: center; gap: 0.75rem; }
            .summary-grid { grid-template-columns: repeat(2, 1fr); }
            .method-grid { grid-template-columns: 1fr; }
            .header-left h1 { font-size: 1.3rem; }
        }

        @media (max-width: 480px) {
            .metrics-grid { grid-template-columns: 1fr 1fr; }
            .summary-grid { grid-template-columns: 1fr; }
            .stock-card { padding: 1rem; }
        }

        /* ===== TOOLTIP ===== */
        [data-tooltip] {
            position: relative;
        }

        [data-tooltip]::before {
            content: attr(data-tooltip);
            position: absolute;
            bottom: calc(100% + 8px);
            left: 50%;
            transform: translateX(-50%) translateY(4px);
            background: var(--bg-card-solid);
            color: var(--text-primary);
            padding: 0.4rem 0.7rem;
            border-radius: 6px;
            font-size: 0.72rem;
            font-weight: 500;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: all var(--transition-fast);
            border: var(--glass-border);
            box-shadow: var(--shadow-md);
            z-index: 100;
        }

        [data-tooltip]:hover::before {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }
    </style>
    <script src="/static/chart.min.js"></script>
    <script>
        if (typeof Chart === 'undefined') {
            document.write('<script src="https://cdn.jsdelivr.net/npm/chart.js"><\/script>');
        }
    </script>
</head>
<body>

<!-- Animated Background -->
<div class="bg-mesh">
    <div class="orb"></div>
    <div class="orb"></div>
    <div class="orb"></div>
    <div class="orb"></div>
</div>

<div class="app-container">
    <!-- HEADER -->
    <header class="header">
        <div class="header-left">
            <h1>Indian Day-Trading Stock Analyzer</h1>
            <div class="subtitle">Historical analysis of NSE India equities for day-trading characteristics</div>
        </div>
        <div class="header-right">
            <!-- Theme Toggle Switch -->
            <div class="theme-switch-wrapper" data-tooltip="Theme: System Default (Click to toggle)">
                <button id="theme-toggle" class="theme-toggle-btn" role="switch" aria-checked="false" aria-label="Toggle dark and light mode" onclick="toggleTheme()">
                    <span class="theme-icon theme-icon-sun" title="Light Mode">☀️</span>
                    <span class="theme-thumb" id="theme-thumb"></span>
                    <span class="theme-icon theme-icon-moon" title="Dark Mode">🌙</span>
                </button>
            </div>
            <span class="live-clock" id="live-clock"></span>
            <div class="header-badge">
                <span class="pulse-dot"></span> NSE India
            </div>
        </div>
    </header>

    <!-- DISCLAIMER -->
    <div class="disclaimer-banner">
        <span class="icon">⚠</span>
        <div class="text">
            <strong>DISCLAIMER:</strong> This is a <strong>historical analysis tool</strong>, not a prediction system.
            Rankings are based strictly on measurable historical data. Past characteristics do not guarantee future results.
            This tool does not constitute financial advice and does not guarantee any profits.
        </div>
    </div>

    <!-- CONTROLS -->
    <div class="controls-panel">
        <div class="control-group">
            <label for="period-select">Analysis Period</label>
            <select id="period-select">
                <option value="15" selected>Last 15 Trading Days (Fastest)</option>
                <option value="30">Last 30 Trading Days</option>
            </select>
        </div>
        <div class="control-group">
            <label for="universe-select">Stock Universe</label>
            <select id="universe-select">
                <option value="NIFTY_50" selected>NIFTY 50 — Large Cap (Fastest)</option>
                <option value="NIFTY_100">NIFTY 100 — Top 100</option>
                <option value="NIFTY_200">NIFTY 200 — Top 200</option>
                <option value="NIFTY_500">NIFTY 500 — Broad Market</option>
            </select>
        </div>
        <button id="btn-analyze" class="btn btn-primary" onclick="startAnalysis()">
            <span id="btn-text">▶ Run Analysis</span>
        </button>
    </div>

    <!-- PROGRESS -->
    <div id="progress-panel" class="progress-panel">
        <div class="progress-header">
            <div class="progress-stage">
                <div class="stage-icon" id="stage-icon">📡</div>
                <div>
                    <div class="stage-text" id="progress-label">Preparing...</div>
                    <div class="stage-sub" id="progress-sub">Initializing data pipeline</div>
                </div>
            </div>
            <span class="progress-count" id="progress-count"></span>
        </div>
        <div class="progress-bar-container">
            <div id="progress-bar" class="progress-bar"></div>
        </div>
        <div class="progress-meta">
            <span style="color:var(--text-muted);font-size:0.75rem;">Processing</span>
            <span class="progress-symbol-tag" id="progress-symbol">—</span>
        </div>
    </div>

    <!-- ERROR -->
    <div id="error-banner" class="error-banner" style="display:none;"></div>

    <!-- RESULTS -->
    <div id="results-container" style="display:none;">
        <!-- Summary Cards -->
        <div id="summary-grid" class="summary-grid"></div>

        <!-- Top 5 Cards -->
        <div class="results-section" id="results-section">
            <div class="section-header">
                <span class="section-title">🏆 Top 5 Stocks — Historical Day-Trading Characteristics</span>
                <div class="export-buttons">
                    <button class="btn btn-export" onclick="exportReport('csv')" data-tooltip="Download as CSV">📊 CSV</button>
                    <button class="btn btn-export" onclick="exportReport('html')" data-tooltip="Download as HTML">📄 HTML</button>
                </div>
            </div>
            <div class="stock-cards-container" id="stock-cards-container"></div>
        </div>

        <!-- Trading Profiles Matrix Chart -->
        <div class="results-section" id="chart-section" style="margin-top: 2rem;">
            <div class="section-header">
                <span class="section-title">📊 Intraday Trading Profiles Matrix</span>
            </div>
            <div class="chart-container" style="position: relative; height:400px; width:100%; background: var(--glass-bg); border-radius: var(--radius-lg); padding: 1.5rem; border: var(--glass-border); box-shadow: var(--shadow-md);">
                <canvas id="profilesChart"></canvas>
            </div>
        </div>

        <!-- Methodology -->
        <div class="methodology-section">
            <h3>📐 Scoring Methodology</h3>
            <div class="method-grid">
                <div class="method-card">
                    <h4>📈 Movement <span class="weight-badge">35%</span></h4>
                    <ul>
                        <li>Average High-Low range %</li>
                        <li>Average Open-Close movement %</li>
                        <li>Median High-Low range %</li>
                    </ul>
                </div>
                <div class="method-card">
                    <h4>📊 Volatility <span class="weight-badge">20%</span></h4>
                    <ul>
                        <li>Normalized Average True Range</li>
                        <li>Daily return standard deviation</li>
                    </ul>
                </div>
                <div class="method-card">
                    <h4>💧 Liquidity <span class="weight-badge">25%</span></h4>
                    <ul>
                        <li>Average daily volume</li>
                        <li>Volume consistency (inverse CV)</li>
                        <li>Recent volume trend</li>
                    </ul>
                </div>
                <div class="method-card">
                    <h4>🎯 Consistency <span class="weight-badge">20%</span></h4>
                    <ul>
                        <li>Movement frequency (active days)</li>
                        <li>Max consecutive active streak</li>
                    </ul>
                </div>
                <div class="method-card">
                    <h4>⚡ Risk Penalty <span class="weight-badge">-10%</span></h4>
                    <ul>
                        <li>Max single-day adverse move</li>
                        <li>Downside deviation</li>
                        <li>Overnight gap frequency</li>
                    </ul>
                </div>
                <div class="method-card">
                    <h4>🔧 Normalization</h4>
                    <p>Min-max normalization to [0, 100] across all eligible stocks. Scores are relative to the analyzed universe.</p>
                </div>
            </div>
        </div>

        <!-- Data Source Info -->
        <div id="data-info" class="methodology-section">
            <h3>📡 Data Source Information</h3>
            <div id="data-info-content"></div>
        </div>

        <!-- Warnings -->
        <div id="warnings-section" class="warnings-section" style="display:none;">
            <h3>⚠️ Data Quality Warnings</h3>
            <div id="warnings-content"></div>
        </div>
    </div>

    <!-- EMPTY STATE -->
    <div id="empty-state" class="empty-state">
        <div class="empty-icon-container">📊</div>
        <h3>Ready to Analyze</h3>
        <p>Select your analysis period and stock universe, then hit <strong>Run Analysis</strong> to discover the top-performing stocks for day trading.</p>
        <div class="empty-steps">
            <div class="empty-step"><span class="step-num">1</span> Choose parameters</div>
            <div class="empty-step"><span class="step-num">2</span> Fetch market data</div>
            <div class="empty-step"><span class="step-num">3</span> View ranked results</div>
        </div>
    </div>

    <!-- FOOTER -->
    <footer class="footer">
        <p>Indian Day-Trading Stock Analyzer — Historical analysis tool, not financial advice</p>
        <p>Data sourced from Yahoo Finance (unofficial). Not affiliated with NSE India.</p>
    </footer>
</div>

<script>
    let pollInterval = null;

    // ===== LIVE CLOCK =====
    function updateClock() {
        const el = document.getElementById('live-clock');
        if (el) {
            const now = new Date();
            el.textContent = now.toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false
            }) + ' IST';
        }
    }
    updateClock();
    setInterval(updateClock, 1000);

    // ===== CONFETTI =====
    function launchConfetti() {
        const container = document.createElement('div');
        container.className = 'confetti-container';
        document.body.appendChild(container);

        const colors = ['#6366f1', '#22d3ee', '#34d399', '#fbbf24', '#f472b6', '#a78bfa', '#fb923c'];
        for (let i = 0; i < 60; i++) {
            const piece = document.createElement('div');
            piece.className = 'confetti-piece';
            piece.style.left = Math.random() * 100 + '%';
            piece.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
            piece.style.animationDuration = (Math.random() * 2 + 1.5) + 's';
            piece.style.animationDelay = Math.random() * 0.8 + 's';
            piece.style.width = (Math.random() * 6 + 4) + 'px';
            piece.style.height = (Math.random() * 6 + 4) + 'px';
            piece.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
            container.appendChild(piece);
        }
        setTimeout(() => container.remove(), 4000);
    }

    // ===== SCORE RING SVG =====
    function createScoreRing(score, gradientId) {
        const radius = 22;
        const circumference = 2 * Math.PI * radius;
        const offset = circumference - (score / 100) * circumference;
        const colors = {
            high: ['#22d3ee', '#6366f1'],
            mid: ['#3b82f6', '#8b5cf6'],
            low: ['#f59e0b', '#ef4444']
        };
        const level = score >= 60 ? 'high' : score >= 35 ? 'mid' : 'low';
        const [c1, c2] = colors[level];

        return `
            <div class="score-ring">
                <svg viewBox="0 0 56 56">
                    <defs>
                        <linearGradient id="${gradientId}" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="${c1}" />
                            <stop offset="100%" stop-color="${c2}" />
                        </linearGradient>
                    </defs>
                    <circle class="ring-bg" cx="28" cy="28" r="${radius}" />
                    <circle class="ring-fill" cx="28" cy="28" r="${radius}"
                        stroke="url(#${gradientId})"
                        stroke-dasharray="${circumference}"
                        stroke-dashoffset="${offset}" />
                </svg>
                <div class="score-text">${score.toFixed(1)}</div>
            </div>
        `;
    }

    // ===== ANALYSIS =====
    async function startAnalysis() {
        const btn = document.getElementById('btn-analyze');
        const btnText = document.getElementById('btn-text');
        const progressPanel = document.getElementById('progress-panel');
        const errorBanner = document.getElementById('error-banner');
        const emptyState = document.getElementById('empty-state');

        btn.disabled = true;
        btnText.innerHTML = '<span class="spinner"></span> Analyzing...';
        progressPanel.classList.add('active');
        errorBanner.style.display = 'none';
        emptyState.style.display = 'none';

        const period = document.getElementById('period-select').value;
        const universe = document.getElementById('universe-select').value;

        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ period: parseInt(period), universe }),
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'Analysis failed to start');
            }

            pollInterval = setInterval(pollProgress, 1000);
        } catch (error) {
            showError(error.message);
            resetButton();
        }
    }

    async function pollProgress() {
        try {
            const response = await fetch('/api/progress');
            const data = await response.json();

            const progressBar = document.getElementById('progress-bar');
            const progressLabel = document.getElementById('progress-label');
            const progressSub = document.getElementById('progress-sub');
            const progressCount = document.getElementById('progress-count');
            const progressSymbol = document.getElementById('progress-symbol');
            const stageIcon = document.getElementById('stage-icon');

            if (data.status === 'fetching') {
                const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
                progressBar.style.width = pct + '%';
                progressLabel.textContent = 'Fetching Market Data';
                progressSub.textContent = `Downloading OHLCV data from Yahoo Finance`;
                progressCount.textContent = `${data.current} / ${data.total}`;
                progressSymbol.textContent = data.symbol || '—';
                stageIcon.textContent = '📡';
            } else if (data.status === 'analyzing') {
                progressBar.style.width = '92%';
                progressLabel.textContent = 'Computing Rankings';
                progressSub.textContent = 'Scoring metrics and ranking stocks';
                progressCount.textContent = '';
                progressSymbol.textContent = 'Analyzing...';
                stageIcon.textContent = '🧮';
            } else if (data.status === 'complete') {
                clearInterval(pollInterval);
                progressBar.style.width = '100%';
                progressLabel.textContent = 'Analysis Complete!';
                progressSub.textContent = 'Your results are ready';
                stageIcon.textContent = '✅';
                launchConfetti();
                await loadResults();
                setTimeout(() => {
                    document.getElementById('progress-panel').classList.remove('active');
                }, 2000);
                resetButton();
            } else if (data.status === 'error') {
                clearInterval(pollInterval);
                showError(data.error || 'Unable to retrieve sufficient market data.');
                document.getElementById('progress-panel').classList.remove('active');
                resetButton();
            }
        } catch (error) {
            // Silently retry
        }
    }

    async function loadResults() {
        try {
            const response = await fetch('/api/results');
            if (!response.ok) throw new Error('Failed to load results');
            const data = await response.json();
            renderResults(data);
        } catch (error) {
            showError('Failed to load results: ' + error.message);
        }
    }

    function renderResults(data) {
        currentTopStocksData = data.top_stocks;
        const container = document.getElementById('results-container');
        const emptyState = document.getElementById('empty-state');
        container.style.display = 'block';
        emptyState.style.display = 'none';

        // Summary cards
        const summaryGrid = document.getElementById('summary-grid');
        const meta = data.metadata;
        const summaryItems = [
            { icon: '📅', label: 'Analysis Period', value: `${meta.analysis_period_days} days`, detail: `${meta.analysis_start_date} → ${meta.analysis_end_date}` },
            { icon: '📈', label: 'Stocks Analyzed', value: meta.total_stocks_analyzed, detail: `of ${meta.total_stocks_in_universe} in universe` },
            { icon: '🚫', label: 'Stocks Excluded', value: meta.total_stocks_excluded, detail: 'insufficient or invalid data' },
            { icon: '⚙️', label: 'Methodology', value: `v${meta.scoring_methodology_version}`, detail: meta.stock_universe },
        ];

        summaryGrid.innerHTML = summaryItems.map((item, i) => `
            <div class="summary-card animate-in stagger-${i + 1}">
                <span class="card-icon">${item.icon}</span>
                <div class="label">${item.label}</div>
                <div class="value">${item.value}</div>
                <div class="detail">${item.detail}</div>
            </div>
        `).join('');

        // Stock cards
        const stockContainer = document.getElementById('stock-cards-container');
        stockContainer.innerHTML = '';

        data.top_stocks.forEach((stock, index) => {
            const gradientId = `scoreGrad${index}`;
            const card = document.createElement('div');
            card.className = `stock-card rank-${stock.rank}-card animate-in`;
            card.style.animationDelay = `${0.15 + index * 0.08}s`;

            card.innerHTML = `
                <div class="stock-card-header">
                    <div class="stock-card-left">
                        <span class="rank-badge rank-${stock.rank}">${stock.rank}</span>
                        <div class="stock-identity">
                            <div class="symbol-name">${stock.symbol}</div>
                            <div class="price-tag">₹${stock.metrics.avg_close_price.toFixed(2)} avg close</div>
                        </div>
                    </div>
                    ${createScoreRing(stock.final_score, gradientId)}
                </div>
                <div class="metrics-grid">
                    <div class="metric-pill pill-movement">
                        <div class="metric-label"><span>Movement</span> <span>🏃</span></div>
                        <div class="metric-value">${stock.movement_score.toFixed(1)}</div>
                        <div class="metric-bar-mini"><div class="metric-bar-mini-fill" style="width:${stock.movement_score}%"></div></div>
                    </div>
                    <div class="metric-pill pill-volatility">
                        <div class="metric-label"><span>Volatility</span> <span>⚡</span></div>
                        <div class="metric-value">${stock.volatility_score.toFixed(1)}</div>
                        <div class="metric-bar-mini"><div class="metric-bar-mini-fill" style="width:${stock.volatility_score}%"></div></div>
                    </div>
                    <div class="metric-pill pill-liquidity">
                        <div class="metric-label"><span>Liquidity</span> <span>💧</span></div>
                        <div class="metric-value">${stock.liquidity_score.toFixed(1)}</div>
                        <div class="metric-bar-mini"><div class="metric-bar-mini-fill" style="width:${stock.liquidity_score}%"></div></div>
                    </div>
                    <div class="metric-pill pill-consistency">
                        <div class="metric-label"><span>Consistency</span> <span>🎯</span></div>
                        <div class="metric-value">${stock.consistency_score.toFixed(1)}</div>
                        <div class="metric-bar-mini"><div class="metric-bar-mini-fill" style="width:${stock.consistency_score}%"></div></div>
                    </div>
                    <div class="metric-pill pill-risk">
                        <div class="metric-label"><span>Risk</span> <span>🛡️</span></div>
                        <div class="metric-value">${stock.risk_penalty.toFixed(1)}</div>
                        <div class="metric-bar-mini"><div class="metric-bar-mini-fill" style="width:${stock.risk_penalty}%"></div></div>
                    </div>
                </div>
                <div class="stock-explanation">${stock.explanation}</div>
            `;
            stockContainer.appendChild(card);
        });

        // Data source info
        const dataInfo = document.getElementById('data-info-content');
        dataInfo.innerHTML = `
            <div class="method-grid">
                <div class="method-card">
                    <h4>Provider</h4>
                    <p>${meta.data_provider}</p>
                    <p style="margin-top:0.4rem;font-size:0.72rem;color:var(--text-muted);">
                        Unofficial wrapper. Not affiliated with or endorsed by NSE India.
                    </p>
                </div>
                <div class="method-card">
                    <h4>Data Retrieved</h4>
                    <p>${new Date(meta.data_retrieval_timestamp).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata'})}</p>
                </div>
            </div>
        `;

        // Warnings
        if (data.warnings_count > 0) {
            document.getElementById('warnings-section').style.display = 'block';
            document.getElementById('warnings-content').innerHTML = `
                <div class="warning-item">
                    <span class="warning-icon">⚠️</span>
                    <div>${data.warnings_count} data quality warning(s) detected during analysis.
                    Export the HTML report for full details.</div>
                </div>
            `;
        }

        // Render Profile Matrix Chart safely
        try {
            renderProfileChart(data.top_stocks);
        } catch (chartErr) {
            console.warn('Profile chart initialization error:', chartErr);
        }

        // Scroll to results smoothly
        setTimeout(() => {
            document.getElementById('results-container').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);
    }

    let profilesChartInstance = null;
    let currentTopStocksData = null;

    function renderProfileChart(topStocks) {
        const chartCanvas = document.getElementById('profilesChart');
        if (!chartCanvas) return;

        if (typeof Chart === 'undefined') {
            console.warn('Chart.js is not available yet. Retrying in 500ms...');
            setTimeout(() => {
                if (typeof Chart !== 'undefined') {
                    renderProfileChart(topStocks);
                } else {
                    const parent = chartCanvas.parentElement;
                    if (parent) {
                        parent.innerHTML = '<div style="text-align:center;padding:2.5rem 1rem;color:var(--text-secondary);font-size:0.85rem;">Interactive Chart is currently unavailable.</div>';
                    }
                }
            }, 500);
            return;
        }

        try {
            const ctx = chartCanvas.getContext('2d');
            
            if (profilesChartInstance) {
                profilesChartInstance.destroy();
            }

            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const textColor = isDark ? '#94a3b8' : '#475569';
            const tickColor = isDark ? '#f8fafc' : '#0f172a';
            const gridColor = isDark ? 'rgba(255, 255, 255, 0.07)' : 'rgba(15, 23, 42, 0.08)';
            const tooltipBg = isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)';
            const tooltipTitle = isDark ? '#f8fafc' : '#0f172a';
            const tooltipBody = isDark ? '#cbd5e1' : '#475569';
            const tooltipBorder = isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(15, 23, 42, 0.1)';

            const labels = topStocks.map(s => s.symbol);
            
            const movementData = topStocks.map(s => s.movement_score);
            const volatilityData = topStocks.map(s => s.volatility_score);
            const liquidityData = topStocks.map(s => s.liquidity_score);
            const consistencyData = topStocks.map(s => s.consistency_score);
            const riskData = topStocks.map(s => s.risk_penalty);

            // Colors matching the design
            const colorBlue = '#60A5FA';
            const colorYellow = '#FBBF24';
            const colorPink = '#F472B6';
            const colorLightPink = '#FBCFE8';
            const colorLightBlue = '#BFDBFE';

            profilesChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Movement', data: movementData, backgroundColor: colorBlue, borderRadius: 4 },
                        { label: 'Volatility', data: volatilityData, backgroundColor: colorYellow, borderRadius: 4 },
                        { label: 'Liquidity', data: liquidityData, backgroundColor: colorPink, borderRadius: 4 },
                        { label: 'Consistency', data: consistencyData, backgroundColor: colorLightPink, borderRadius: 4 },
                        { label: 'Risk', data: riskData, backgroundColor: colorLightBlue, borderRadius: 4 }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                            align: 'start',
                            labels: {
                                color: textColor,
                                usePointStyle: true,
                                boxWidth: 8
                            }
                        },
                        tooltip: {
                            backgroundColor: tooltipBg,
                            titleColor: tooltipTitle,
                            bodyColor: tooltipBody,
                            borderColor: tooltipBorder,
                            borderWidth: 1,
                            padding: 10
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 110, // A bit of padding above 100
                            grid: { color: gridColor, drawBorder: false },
                            ticks: { color: textColor, stepSize: 20 },
                            title: { display: true, text: 'Normalized Score (0-100)', color: textColor }
                        },
                        x: {
                            grid: { display: false, drawBorder: false },
                            ticks: { color: tickColor, font: { weight: 'bold' } },
                            title: { display: true, text: 'Stocks', color: textColor, font: { weight: 'bold' } }
                        }
                    },
                    animation: {
                        duration: 1200,
                        easing: 'easeOutQuart'
                    }
                }
            });
        } catch (err) {
            console.error('Error in renderProfileChart:', err);
        }
    }

    // ===== THEME MANAGEMENT =====
    const THEME_STORAGE_KEY = 'stock_analyzer_theme';

    function getSystemTheme() {
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || getSystemTheme();
    }

    function updateThemeUI(theme) {
        const toggleBtn = document.getElementById('theme-toggle');
        if (!toggleBtn) return;
        const isDark = theme === 'dark';
        toggleBtn.setAttribute('aria-checked', isDark ? 'true' : 'false');
        toggleBtn.setAttribute('title', `Current: ${isDark ? 'Dark' : 'Light'} Mode (Click to switch)`);
        const wrapper = toggleBtn.closest('.theme-switch-wrapper');
        if (wrapper) {
            const isUserSet = localStorage.getItem(THEME_STORAGE_KEY) !== null;
            const sourceText = isUserSet ? 'Saved preference' : 'System default';
            wrapper.setAttribute('data-tooltip', `${isDark ? 'Dark' : 'Light'} Mode (${sourceText}) — Click to toggle`);
        }
    }

    function applyTheme(theme, save = false) {
        document.documentElement.setAttribute('data-theme', theme);
        updateThemeUI(theme);
        if (save) {
            try {
                localStorage.setItem(THEME_STORAGE_KEY, theme);
            } catch (e) {}
        }
        if (profilesChartInstance && currentTopStocksData) {
            renderProfileChart(currentTopStocksData);
        }
    }

    function toggleTheme() {
        const current = getCurrentTheme();
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next, true);
    }

    // React to system color scheme changes if user hasn't explicitly chosen
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            try {
                if (!localStorage.getItem(THEME_STORAGE_KEY)) {
                    applyTheme(e.matches ? 'dark' : 'light', false);
                }
            } catch (err) {}
        });
    }

    // Sync button state on initial page ready
    document.addEventListener('DOMContentLoaded', () => {
        try {
            const stored = localStorage.getItem(THEME_STORAGE_KEY);
            const activeTheme = stored || getSystemTheme();
            applyTheme(activeTheme, false);
        } catch (err) {}
    });

    function showError(message) {
        const errorBanner = document.getElementById('error-banner');
        errorBanner.innerHTML = '❌ ' + message;
        errorBanner.style.display = 'flex';
    }

    function resetButton() {
        const btn = document.getElementById('btn-analyze');
        const btnText = document.getElementById('btn-text');
        btn.disabled = false;
        btnText.innerHTML = '▶ Run Analysis';
    }

    function exportReport(format) {
        window.open(`/api/export/${format}`, '_blank');
    }
</script>
</body>
</html>
"""
