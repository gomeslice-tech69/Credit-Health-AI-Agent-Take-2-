#!/usr/bin/env python3
"""
Export analysis results to JSON for the hosted web version.

    python3 export_web.py

WHY THIS EXISTS

The Streamlit app runs Python live, so it can fetch any ticker on demand. A
page hosted as static files cannot: there is no Python process behind it.

Rather than reimplement the finance in JavaScript -- which would break the
project's central rule that Python does all the arithmetic, and would give two
codebases that could silently disagree -- this script runs the real engine over
a fixed set of companies and writes every result it produced to JSON.

That includes the downside stress test at EVERY slider position (0% to 50% in
5% steps). So when a visitor drags the slider on the hosted page, the page is
not calculating anything. It is looking up a number Python already computed.
The browser does no finance at all.

The trade-off, stated plainly: the hosted version covers a fixed list of
companies and is current as of the day this script was last run. The Streamlit
app is the live tool. Both call the same functions, so their numbers agree.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from typing import Any, Dict, List, Optional

from screener.data_loader import DataLoadError, load_history
from screener.metrics import compute_all_metrics
from screener.narrative import (build_narrative, restructuring_watch,
                                scenario_explanation, structural_caveats)
from screener.rating import rate_stress
from screener.peers import compare_to_peers, median
from screener.scenario import run_ebitda_downside
from screener.signals import evaluate_signals

# The slider positions precomputed for the hosted page. Must match the step
# used by the page's slider control.
HAIRCUTS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

# A deliberately varied teaching set: a stressed airline, the captive-finance
# trap, leveraged media and telco, a healthy consumer staple, a net-cash
# software company, plus the two synthetic files.
COMPANIES: List[Dict[str, str]] = [
    # A deliberately broad teaching set: well-known names across industries
    # with genuinely different credit profiles, so a reader can see what
    # "2x leverage" and "9x leverage" actually look like side by side.
    #
    # Add or remove tickers here and re-run this script to change the hosted
    # set. The Streamlit app needs no list at all -- it fetches any ticker on
    # demand.

    # Airlines -- capital intensive, cyclical, historically leveraged
    {"ticker": "AAL", "source": "yfinance"},
    {"ticker": "DAL", "source": "yfinance"},
    {"ticker": "UAL", "source": "yfinance"},
    {"ticker": "LUV", "source": "yfinance"},

    # Autos -- note F and GM both carry captive finance arms
    {"ticker": "F", "source": "yfinance"},
    {"ticker": "GM", "source": "yfinance"},
    {"ticker": "TSLA", "source": "yfinance"},

    # Cruise and travel -- among the most leveraged large caps
    {"ticker": "CCL", "source": "yfinance"},
    {"ticker": "RCL", "source": "yfinance"},
    {"ticker": "NCLH", "source": "yfinance"},
    {"ticker": "MAR", "source": "yfinance"},

    # Retail -- a sector with wide dispersion between winners and strugglers
    {"ticker": "WMT", "source": "yfinance"},
    {"ticker": "TGT", "source": "yfinance"},
    {"ticker": "M", "source": "yfinance"},
    {"ticker": "KSS", "source": "yfinance"},
    {"ticker": "BBY", "source": "yfinance"},

    # Media and telecom -- large debt loads against stable cash flows
    {"ticker": "T", "source": "yfinance"},
    {"ticker": "VZ", "source": "yfinance"},
    {"ticker": "CMCSA", "source": "yfinance"},
    {"ticker": "DIS", "source": "yfinance"},
    {"ticker": "WBD", "source": "yfinance"},
    {"ticker": "PARA", "source": "yfinance"},

    # Technology -- typically net cash, the opposite end of the scale
    {"ticker": "MSFT", "source": "yfinance"},
    {"ticker": "AAPL", "source": "yfinance"},
    {"ticker": "ORCL", "source": "yfinance"},
    {"ticker": "IBM", "source": "yfinance"},
    {"ticker": "INTC", "source": "yfinance"},

    # Consumer staples -- steady earnings, moderate leverage
    {"ticker": "KO", "source": "yfinance"},
    {"ticker": "PEP", "source": "yfinance"},
    {"ticker": "PG", "source": "yfinance"},
    {"ticker": "KHC", "source": "yfinance"},

    # Healthcare
    {"ticker": "PFE", "source": "yfinance"},
    {"ticker": "CVS", "source": "yfinance"},

    # Industrials and energy
    {"ticker": "BA", "source": "yfinance"},
    {"ticker": "CAT", "source": "yfinance"},
    {"ticker": "XOM", "source": "yfinance"},

    # Synthetic teaching files -- work with no internet at all
    {"ticker": "EXMPL", "source": "local"},
    {"ticker": "HEALTHY", "source": "local"},
]


def _round(value: Optional[float], places: int = 4) -> Optional[float]:
    """Round for a compact file, keeping None as None."""
    return None if value is None else round(value, places)


def analyze(ticker: str, source: str) -> Optional[Dict[str, Any]]:
    """Run the full pipeline and flatten the result into plain JSON types."""
    try:
        history = load_history(ticker, source=source, max_years=5)
    except DataLoadError as exc:
        print(f"  SKIPPED {ticker}: {str(exc).splitlines()[0]}")
        return None

    if len(history.years) < 2:
        print(f"  SKIPPED {ticker}: only {len(history.years)} year(s)")
        return None

    metrics = compute_all_metrics(history)
    signals = evaluate_signals(history, metrics)
    years = history.sorted_years()
    rating = rate_stress(metrics, [(fy.year, fy.ebitda) for fy in years])
    base_scenario = run_ebitda_downside(years[-1], years[-2], haircut=0.20)
    narrative = build_narrative(history, metrics, signals, base_scenario,
                                rating)
    watch_headline, watch_items = restructuring_watch(rating, signals, metrics)

    by_year = {fy.year: fy for fy in years}
    rows = []
    for m in metrics:
        fy = by_year[m.year]
        rows.append({
            "year": m.year,
            "revenue": _round(fy.revenue, 1),
            "ebitda": _round(fy.ebitda, 1),
            "cash": _round(fy.cash, 1),
            "totalDebt": _round(fy.total_debt, 1),
            "interestExpense": _round(fy.interest_expense, 1),
            "operatingCashFlow": _round(fy.operating_cash_flow, 1),
            "capex": _round(fy.capex, 1),
            "netDebt": _round(m.net_debt, 1),
            "debtToEbitda": _round(m.debt_to_ebitda),
            "netDebtToEbitda": _round(m.net_debt_to_ebitda),
            "interestCoverage": _round(m.interest_coverage),
            "freeCashFlow": _round(m.free_cash_flow, 1),
            "ebitdaMargin": _round(m.ebitda_margin),
            "revenueGrowth": _round(m.revenue_growth),
            "reasons": m.reasons,
        })

    # Every slider position, computed here in Python so the browser never has
    # to. This is the whole point of the export.
    scenarios = {}
    for pct in HAIRCUTS:
        result = run_ebitda_downside(years[-1], years[-2], haircut=pct / 100.0)
        scenarios[str(pct)] = {
            "meaningful": result.meaningful,
            "note": result.note,
            "baseEbitda": _round(result.base_ebitda, 1),
            "stressedEbitda": _round(result.stressed_ebitda, 1),
            "base": {
                "debtToEbitda": _round(result.base.debt_to_ebitda),
                "netDebtToEbitda": _round(result.base.net_debt_to_ebitda),
                "interestCoverage": _round(result.base.interest_coverage),
            },
            "stressed": {
                "debtToEbitda": _round(result.stressed.debt_to_ebitda),
                "netDebtToEbitda": _round(result.stressed.net_debt_to_ebitda),
                "interestCoverage": _round(result.stressed.interest_coverage),
            },
            "explanation": scenario_explanation(result),
        }

    return {
        "ticker": history.ticker,
        "companyName": history.company_name,
        "shortName": history.short_name,
        "sector": history.sector,
        "industry": history.industry,
        "currency": history.currency,
        "units": history.units,
        "source": history.source,
        "provenance": history.provenance,
        "dataNotes": history.notes,
        "isSynthetic": "SYNTHETIC" in history.company_name.upper(),
        "missingLatest": years[-1].missing_fields(),
        "years": rows,
        "rating": {
            "label": rating.rating,
            "score": rating.score,
            "maxScore": rating.max_score,
            "ratio": _round(rating.ratio, 4),
            "assessedCount": rating.assessed_count,
            "confidenceNote": rating.confidence_note,
            "factors": [{
                "name": f.name,
                "points": f.points,
                "maxPoints": f.max_points,
                "observation": f.observation,
                "thresholdNote": f.threshold_note,
            } for f in rating.factors],
        },
        "signals": [{
            "name": s.name,
            "status": s.status,
            "detail": s.detail,
            "whyItMatters": s.why_it_matters,
        } for s in signals],
        "narrative": {
            "headline": narrative.headline,
            "whatIsHappening": narrative.what_is_happening,
            "whyItMatters": narrative.why_it_matters,
            "ratingReasons": narrative.rating_reasons,
        },
        "caveats": [{"title": t, "explanation": e}
                    for t, e in structural_caveats(history, metrics)],
        "restructuringWatch": {
            "headline": watch_headline,
            "items": [{"area": a, "why": w} for a, w in watch_items],
        },
        "scenarios": scenarios,
    }



# ---------------------------------------------------------------------------
# Peer comparison
# ---------------------------------------------------------------------------

# A median built from two or three companies is not a benchmark, it is an
# anecdote. Below this count the comparison is withheld and the page says why,
# rather than printing a number that looks authoritative and is not.
MIN_PEERS = 4

# Which way is "worse" for each metric. Getting this backwards silently
# inverts every conclusion, so it is stated explicitly rather than inferred.
PEER_METRICS = [
    ("netDebtToEbitda", "Net Debt / EBITDA", True),
    ("interestCoverage", "Interest Coverage", False),
    ("ebitdaMargin", "EBITDA Margin", False),
]


def build_peer_comparisons(exported: List[Dict[str, Any]]) -> None:
    """Attach a sector comparison to each company, in place.

    Two exclusions matter and are deliberate:

      * A company is never its own peer. Including it would drag the median
        toward the very value being judged against it.
      * Synthetic teaching companies are excluded from every median. Their
        figures are invented, so letting them shape a real benchmark would
        quietly corrupt it.

    Medians, not means: credit ratios carry severe outliers (one company with
    near-zero EBITDA produces a 400x reading) and a single such value would
    destroy a mean. Companies whose metric could not be computed are dropped
    from the median rather than counted as zero, and the count of dropped
    peers is reported alongside the result.
    """
    real = [c for c in exported if not c["isSynthetic"]]

    for company in exported:
        sector = company.get("sector")
        peers = [c for c in real
                 if c.get("sector") == sector and c["ticker"] != company["ticker"]]

        if company["isSynthetic"] or not sector or len(peers) < MIN_PEERS:
            if company["isSynthetic"]:
                reason = ("This is synthetic teaching data, so it is not "
                          "compared against real companies.")
            elif not sector:
                reason = "No sector was reported for this company."
            else:
                reason = (f"Only {len(peers)} other {sector} companies are in "
                          f"this set. A median needs at least {MIN_PEERS} "
                          "peers to mean anything, so no comparison is shown.")
            company["peers"] = {"available": False, "reason": reason,
                                "sector": sector, "peerCount": len(peers),
                                "metrics": []}
            continue

        latest = company["years"][-1]
        rows = []
        for key, label, higher_is_worse in PEER_METRICS:
            peer_values = [c["years"][-1][key] for c in peers]
            result = compare_to_peers(latest[key], peer_values, label,
                                      higher_is_worse=higher_is_worse)
            rows.append({
                "key": key,
                "label": label,
                "companyValue": _round(result["company_value"]),
                "peerMedian": _round(result["peer_median"]),
                "percentile": _round(result["percentile"], 1),
                "peersUsed": result["peers_used"],
                "peersDropped": result["peers_dropped"],
                "higherIsWorse": higher_is_worse,
                "sentence": result["sentence"],
            })

        company["peers"] = {
            "available": True,
            "sector": sector,
            "peerCount": len(peers),
            "peerTickers": sorted(c["ticker"] for c in peers),
            "metrics": rows,
        }


def main() -> int:
    print(f"Exporting {len(COMPANIES)} companies...")
    results = []
    failures = []
    for i, entry in enumerate(COMPANIES):
        print(f"  [{i + 1}/{len(COMPANIES)}] {entry['ticker']}...", end=" ",
              flush=True)
        try:
            data = analyze(entry["ticker"], entry["source"])
        except Exception as exc:  # one bad ticker must not lose the whole run
            print(f"ERROR: {exc}")
            failures.append(entry["ticker"])
            continue
        if data:
            print(f"OK - {data['rating']['label']}")
            results.append(data)
        else:
            failures.append(entry["ticker"])
        # Yahoo rate-limits rapid bursts. A short pause costs a few seconds
        # once and avoids losing half the set to throttling.
        if entry["source"] == "yfinance" and i < len(COMPANIES) - 1:
            time.sleep(0.6)

    if failures:
        print(f"\n  Could not export: {', '.join(failures)}")

    if not results:
        print("No companies exported.", file=sys.stderr)
        return 1

    build_peer_comparisons(results)
    compared = sum(1 for c in results if c["peers"]["available"])
    print(f"  Peer comparison attached for {compared} of {len(results)} "
          f"companies (min {MIN_PEERS} sector peers required)")

    payload = {
        "generated": date.today().isoformat(),
        "haircuts": HAIRCUTS,
        "companies": results,
    }
    with open("web_data.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    import os
    size = os.path.getsize("web_data.json")
    print(f"\nWrote web_data.json — {len(results)} companies, "
          f"{size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
