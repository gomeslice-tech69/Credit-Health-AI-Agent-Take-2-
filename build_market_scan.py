#!/usr/bin/env python3
"""
Build the market-scan dataset: every benchmark company, fully screened.

    python3 build_market_scan.py

WHY THIS EXISTS

Screening one company is something anyone can do by reading a filing. Screening
thirty-six with one consistent ruler is not -- and it is the capability that
separates an instrument from an opinion. Ask a person (or a language model)
about thirty-six companies and you get thirty-six incomparable answers, each
framed differently. Here every company meets the same thresholds, so the
rankings mean something.

Running the full engine per company at page load would take minutes and get the
app rate-limited, so the whole set is screened once here and written to
data/market_scan.json (~40 KB, committed). The app reads it with no network
access at all.

The trade-off, stated plainly: the scan is a snapshot from the day this last
ran, while a single-company screen is live. The interface shows the date.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from typing import Any, Dict, List

from screener.altman import compute_z_score, is_meaningful_for
from screener.applicability import assess
from screener.data_loader import DataLoadError, load_history
from screener.metrics import compute_all_metrics
from screener.rating import rate_stress, rating_trajectory
from screener.signals import evaluate_signals

from build_peer_cache import BENCHMARK_TICKERS

OUTPUT = "data/market_scan.json"


def screen(ticker: str) -> Dict[str, Any]:
    """Run the full engine over one company and flatten the result."""
    history = load_history(ticker, source="yfinance", max_years=5)
    if len(history.years) < 2:
        raise DataLoadError(f"Only {len(history.years)} year(s) for {ticker}")

    # Banks and insurers are excluded outright. Their ratios do not carry the
    # usual meaning, and a bank sitting in a ranked list of stress scores
    # misleads about both the bank and everything near it.
    applies = assess(history.sector, history.industry)
    if not applies.can_rate:
        raise DataLoadError(f"{ticker}: {applies.headline}")

    metrics = compute_all_metrics(history)
    years = history.sorted_years()
    signals = evaluate_signals(history, metrics)
    rating = rate_stress(metrics, [(fy.year, fy.ebitda) for fy in years])
    latest = metrics[-1]

    z = compute_z_score(years[-1])
    z_ok, _ = is_meaningful_for(history.sector)

    trail = rating_trajectory(history, compute_all_metrics)

    def r(v, places=2):
        return None if v is None else round(v, places)

    return {
        "ticker": history.ticker,
        "name": history.short_name,
        "sector": history.sector,
        "industry": history.industry,
        "currency": history.currency,
        "units": history.units,
        "year": years[-1].year,
        "rating": rating.rating,
        "score": rating.score,
        "maxScore": rating.max_score,
        "ratio": r(rating.ratio, 4),
        "assessed": rating.assessed_count,
        "netDebtToEbitda": r(latest.net_debt_to_ebitda),
        "debtToEbitda": r(latest.debt_to_ebitda),
        "interestCoverage": r(latest.interest_coverage),
        "freeCashFlow": r(latest.free_cash_flow, 1),
        "ebitdaMargin": r(latest.ebitda_margin, 4),
        "revenueGrowth": r(latest.revenue_growth, 4),
        "revenue": r(years[-1].revenue, 1),
        "ebitda": r(years[-1].ebitda, 1),
        "totalDebt": r(years[-1].total_debt, 1),
        "cash": r(years[-1].cash, 1),
        "signalsFired": sum(1 for s in signals if s.status == "fired"),
        "signalsTotal": len(signals),
        "firedNames": [s.name for s in signals if s.status == "fired"],
        "zScore": r(z.score) if (z.available and z_ok) else None,
        "zZone": z.zone if (z.available and z_ok) else None,
        "trajectory": [{"year": p.year, "ratio": r(p.ratio, 4),
                        "rating": p.rating} for p in trail],
        "factors": [{"name": f.name, "points": f.points,
                     "max": f.max_points} for f in rating.factors],
    }


def main() -> int:
    print(f"Screening {len(BENCHMARK_TICKERS)} companies...")
    rows: List[Dict[str, Any]] = []
    failed: List[str] = []

    for i, ticker in enumerate(BENCHMARK_TICKERS):
        print(f"  [{i + 1}/{len(BENCHMARK_TICKERS)}] {ticker}...",
              end=" ", flush=True)
        try:
            row = screen(ticker)
        except Exception as exc:
            print(f"skipped ({str(exc).splitlines()[0][:40]})")
            failed.append(ticker)
            continue
        print(f"{row['rating']}")
        rows.append(row)
        if i < len(BENCHMARK_TICKERS) - 1:
            time.sleep(0.6)

    if not rows:
        print("Nothing screened.", file=sys.stderr)
        return 1

    # Rank by stress, worst first. Companies with the same ratio are ordered by
    # how many signals fired, so the tie-break still carries information.
    rows.sort(key=lambda x: (-(x["ratio"] or 0), -x["signalsFired"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    sectors: Dict[str, List[float]] = {}
    for row in rows:
        if row["sector"] and row["ratio"] is not None:
            sectors.setdefault(row["sector"], []).append(row["ratio"])

    payload = {
        "generated": date.today().isoformat(),
        "companies": rows,
        "sectorMedians": {
            s: round(sorted(v)[len(v) // 2] if len(v) % 2 else
                     (sorted(v)[len(v) // 2 - 1] + sorted(v)[len(v) // 2]) / 2, 4)
            for s, v in sectors.items() if len(v) >= 3
        },
        "failed": failed,
    }
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    import os
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["rating"]] = counts.get(row["rating"], 0) + 1
    print(f"\nWrote {OUTPUT} — {len(rows)} companies, "
          f"{os.path.getsize(OUTPUT) / 1024:.0f} KB")
    for label in ("Elevated Stress", "Moderate Stress", "Low Stress"):
        print(f"  {label:<18} {counts.get(label, 0)}")
    if failed:
        print(f"  not screened: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
