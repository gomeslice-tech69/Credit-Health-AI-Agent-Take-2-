#!/usr/bin/env python3
"""
Build the sector peer benchmark that the live app compares against.

    python3 build_peer_cache.py

WHY A CACHE RATHER THAN LIVE FETCHING

The Streamlit app screens any ticker on demand, so a peer comparison could in
principle fetch the whole peer group each time. It must not. Thirty-eight
network requests per analysis would make every lookup take a minute and would
get the app rate-limited by Yahoo within a few uses -- on a shared cloud host,
quickly and permanently.

Instead this script fetches the benchmark group ONCE, reduces it to the few
numbers a comparison needs, and writes them to data/peer_cache.json. That file
is committed to the repository, so it ships with the app and loads instantly
with no network access at all.

The trade-off, stated plainly: the benchmark is a snapshot from the day this
script last ran, while the company being analysed is live. Comparing a current
figure against a benchmark from a few weeks ago is normal practice -- industry
medians move slowly -- but the app displays the benchmark date so a reader can
judge for themselves. Re-run this script to refresh it.

Only the raw per-peer values are stored, not the median. The median and
percentile are recomputed at runtime by screener/peers.py, so the statistics
live in one tested place rather than being frozen into a data file.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from typing import Any, Dict, List

from screener.data_loader import DataLoadError, load_history
from screener.metrics import compute_all_metrics

# The benchmark group. These are the companies the medians are built from --
# the same list the static site uses, minus the synthetic teaching files, which
# must never shape a real benchmark.
BENCHMARK_TICKERS = [
    "AAL", "DAL", "UAL", "LUV",
    "F", "GM", "TSLA",
    "CCL", "RCL", "NCLH", "MAR",
    "WMT", "TGT", "M", "KSS", "BBY",
    "T", "VZ", "CMCSA", "DIS", "WBD", "PARA",
    "MSFT", "AAPL", "ORCL", "IBM", "INTC",
    "KO", "PEP", "PG", "KHC",
    "PFE", "CVS",
    "BA", "CAT", "XOM",
]

# Metrics the comparison covers, and which direction is worse. Stating this
# explicitly matters: inferring it would silently invert every verdict.
PEER_METRICS = [
    ("net_debt_to_ebitda", "Net Debt / EBITDA", True),
    ("interest_coverage", "Interest Coverage", False),
    ("ebitda_margin", "EBITDA Margin", False),
]

OUTPUT = "data/peer_cache.json"


def main() -> int:
    print(f"Building peer benchmark from {len(BENCHMARK_TICKERS)} companies...")
    sectors: Dict[str, Dict[str, Any]] = {}
    failures: List[str] = []

    for i, ticker in enumerate(BENCHMARK_TICKERS):
        print(f"  [{i + 1}/{len(BENCHMARK_TICKERS)}] {ticker}...", end=" ",
              flush=True)
        try:
            history = load_history(ticker, source="yfinance", max_years=2)
        except (DataLoadError, Exception) as exc:
            print(f"skipped ({str(exc).splitlines()[0][:50]})")
            failures.append(ticker)
            continue

        sector = history.sector
        if not sector or not history.years:
            print("skipped (no sector reported)")
            failures.append(ticker)
            continue

        latest = compute_all_metrics(history)[-1]
        entry = sectors.setdefault(
            sector, {"tickers": [], "values": {k: [] for k, _, _ in PEER_METRICS}})
        entry["tickers"].append(ticker)
        for key, _, _ in PEER_METRICS:
            # None is preserved rather than dropped here. peers.py excludes it
            # from the median and reports how many were excluded, which is
            # information a reader should see.
            entry["values"][key].append(getattr(latest, key))

        print(f"OK ({sector})")
        if i < len(BENCHMARK_TICKERS) - 1:
            time.sleep(0.6)  # Yahoo rate-limits bursts

    if not sectors:
        print("No benchmark data could be built.", file=sys.stderr)
        return 1

    payload = {
        "generated": date.today().isoformat(),
        "metrics": [{"key": k, "label": lbl, "higherIsWorse": hw}
                    for k, lbl, hw in PEER_METRICS],
        "sectors": {s: {"tickers": sorted(d["tickers"]),
                        "count": len(d["tickers"]),
                        "values": d["values"]}
                    for s, d in sorted(sectors.items())},
    }
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    import os
    print(f"\nWrote {OUTPUT} — {len(sectors)} sectors, "
          f"{sum(d['count'] for d in payload['sectors'].values())} companies, "
          f"{os.path.getsize(OUTPUT) / 1024:.0f} KB")
    for s, d in sorted(payload["sectors"].items(),
                       key=lambda kv: -kv[1]["count"]):
        print(f"  {s:<24} {d['count']:>2}  {', '.join(d['tickers'])}")
    if failures:
        print(f"\n  Not included: {', '.join(failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
