#!/usr/bin/env python3
"""
Financial Distress Screening Agent -- command line entry point.

Usage:
    python3 main.py --ticker EXMPL
    python3 main.py --ticker AAPL --source yfinance
    python3 main.py --ticker EXMPL --scenario 0.30
    python3 main.py --ticker EXMPL --save report.txt

This file is intentionally thin. It parses arguments, calls the four stages in
order, and prints the result. All the finance lives in screener/.
"""

from __future__ import annotations

import argparse
import sys

from screener.data_loader import DataLoadError, load_history
from screener.metrics import compute_all_metrics
from screener.rating import rate_stress
from screener.report import build_report
from screener.scenario import run_ebitda_downside
from screener.signals import evaluate_signals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Screen a public company for signs of financial stress.",
        epilog="This is a screening tool for learning purposes. It is not "
               "investment advice and does not predict bankruptcy.",
    )
    parser.add_argument("--ticker", "-t", required=True,
                        help="Company ticker, e.g. EXMPL or AAPL")
    parser.add_argument("--source", "-s", default="local",
                        choices=["local", "yfinance"],
                        help="Where to get the data (default: local)")
    parser.add_argument("--scenario", type=float, default=0.20,
                        help="EBITDA decline for the downside case, as a "
                             "decimal (default: 0.20 = a 20%% fall)")
    parser.add_argument("--years", type=int, default=5,
                        help="Maximum fiscal years to fetch (default: 5)")
    parser.add_argument("--save", metavar="PATH",
                        help="Also write the report to this file")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not 0 <= args.scenario < 1:
        print(f"Error: --scenario must be between 0 and 1 (got {args.scenario}). "
              "Use 0.20 for a 20% decline.", file=sys.stderr)
        return 2

    # --- Stage 1: get the data -------------------------------------------
    try:
        history = load_history(args.ticker, source=args.source,
                               max_years=args.years)
    except DataLoadError as exc:
        print(f"Could not load data for '{args.ticker}':\n\n{exc}",
              file=sys.stderr)
        return 1

    if not history.years:
        print(f"No fiscal years returned for '{args.ticker}'.", file=sys.stderr)
        return 1

    # --- Stage 2: compute -------------------------------------------------
    metrics = compute_all_metrics(history)
    signals = evaluate_signals(history, metrics)

    years = history.sorted_years()
    latest = years[-1]
    prior = years[-2] if len(years) >= 2 else None
    scenario_result = run_ebitda_downside(latest, prior, haircut=args.scenario)

    rating = rate_stress(metrics, [(fy.year, fy.ebitda) for fy in years])

    # --- Stage 3: report --------------------------------------------------
    report = build_report(history, metrics, signals, scenario_result, rating)
    print(report)

    if args.save:
        try:
            with open(args.save, "w", encoding="utf-8") as fh:
                fh.write(report)
            print(f"[Report saved to {args.save}]")
        except OSError as exc:
            print(f"Could not write to {args.save}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
