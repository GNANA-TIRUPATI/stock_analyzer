# Scoring Methodology — v1.0

## Overview

The Indian Day-Trading Stock Analyzer ranks stocks using a transparent, reproducible scoring model based on **five categories** of historical characteristics. This document details every metric, formula, weight, normalization method, and the final score calculation.

> **IMPORTANT**: This methodology evaluates *historical* characteristics only. It does NOT predict future performance, guarantee profits, or constitute financial advice.

---

## 1. Final Score Formula

```
Final Score = (Movement_Score × 0.30)
            + (Volatility_Score × 0.20)
            + (Liquidity_Score × 0.25)
            + (Consistency_Score × 0.15)
            - (Risk_Penalty × 0.10)
```

All category scores are normalized to [0, 100] before weighting.

---

## 2. Normalization Method

**Min-Max Normalization** across all eligible stocks in the universe:

```
normalized = (value - min_across_stocks) / (max_across_stocks - min_across_stocks) × 100
```

For **inverse metrics** (where lower values are better, e.g., Volume CV):

```
normalized = (1 - (value - min) / (max - min)) × 100
```

**Edge case**: If all stocks have the same value for a metric, all receive 50.0 (midpoint).

---

## 3. Category A: Intraday Price Movement (30%)

Measures how much the stock moves within a single trading session.

### Metrics

| Metric | Formula | Sub-weight |
|---|---|---|
| Average HL Range % | `mean( (High_i - Low_i) / Low_i × 100 )` | 0.40 |
| Average OC Move % | `mean( abs(Close_i - Open_i) / Open_i × 100 )` | 0.30 |
| Median HL Range % | `median( (High_i - Low_i) / Low_i × 100 )` | 0.30 |

**Movement Score** = `0.40 × norm(avg_hl) + 0.30 × norm(avg_oc) + 0.30 × norm(median_hl)`

### Rationale
- **HL Range** captures the total price swing available to day traders
- **OC Move** measures directional movement (net session change)
- **Median** provides a robust central tendency resistant to one extreme day

---

## 4. Category B: Volatility (20%)

Measures historical price variability.

### Metrics

| Metric | Formula | Sub-weight |
|---|---|---|
| Normalized ATR | `mean(TR) / mean(Close) × 100` where `TR = max(H-L, abs(H-PrevC), abs(L-PrevC))` | 0.50 |
| Daily Return Std | `std( (Close_t - Close_{t-1}) / Close_{t-1} )` | 0.50 |

**Volatility Score** = `0.50 × norm(n_atr) + 0.50 × norm(ret_std)`

### Rationale
- **ATR** is the industry-standard volatility measure that accounts for overnight gaps
- **Daily Return Std** captures close-to-close variability

---

## 5. Category C: Volume / Liquidity (25%)

Measures trading activity and liquidity.

### Metrics

| Metric | Formula | Sub-weight |
|---|---|---|
| Average Volume | `mean(Volume_i)` (excluding zero-volume days) | 0.50 |
| Volume Consistency | `std(Volume) / mean(Volume)` — **inverse normalized** | 0.30 |
| Relative Volume Trend | `mean(Volume last 5 days) / mean(Volume all days)` | 0.20 |

**Liquidity Score** = `0.50 × norm(avg_vol) + 0.30 × norm_inv(vol_cv) + 0.20 × norm(rel_vol)`

### Rationale
- **Average Volume** ensures the stock is liquid enough for day trading
- **Volume Consistency** (inverse) rewards stocks with stable daily volume
- **Volume Trend** detects increasing market interest

---

## 6. Category D: Consistency (15%)

Measures how frequently the stock shows meaningful movement.

### Metrics

| Metric | Formula | Sub-weight |
|---|---|---|
| Movement Frequency | `count(HL_range%_i > threshold) / total_days` | 0.60 |
| Max Consecutive Active Days | Longest streak of "active" days | 0.40 |

**Threshold** = `median(HL_range%) × 0.50` (adaptive, per stock)

**Consistency Score** = `0.60 × norm(freq) + 0.40 × norm(streak)`

### Rationale
- A stock with one spike day and 29 flat days is poor for day trading
- **Movement Frequency** rewards regular opportunity
- **Streak Length** rewards consecutive active days (predictability of opportunity)

---

## 7. Category E: Risk Penalty (-10%)

Penalizes stocks with adverse risk characteristics.

### Metrics

| Metric | Formula | Sub-weight |
|---|---|---|
| Max Adverse Move | `max(abs(daily_return_t))` | 0.40 |
| Downside Deviation | `std(negative daily returns)` | 0.30 |
| Gap Risk | `count(abs(Open-PrevClose)/PrevClose > 2%) / total_days` | 0.30 |

**Risk Penalty** = `0.40 × norm(max_adv) + 0.30 × norm(down_dev) + 0.30 × norm(gap)`

### Rationale
- **Max Adverse Move** captures worst-case single-day exposure
- **Downside Deviation** is an asymmetric risk measure (more relevant than symmetric std)
- **Gap Risk** measures overnight gap frequency (uncontrollable for day traders)

---

## 8. Configuration

All weights and thresholds are configurable via `app/config/scoring_weights.yaml`.

Category weights must sum to 1.0 (excluding risk penalty).
Sub-metric weights within each category must sum to 1.0.

The YAML file is validated at application startup.

---

## 9. Tie-Breaking

When two stocks have identical final scores, ties are broken by **average daily volume** (higher volume preferred). This ensures deterministic, reproducible rankings.

---

## 10. Version History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2025 | Initial methodology |
