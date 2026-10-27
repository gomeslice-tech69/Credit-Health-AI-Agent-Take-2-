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

from screener.applicability import assess
from screener.data_loader import DataLoadError, load_history
from screener.metrics import compute_all_metrics

# The benchmark group. These are the companies the medians are built from --
# the same list the static site uses, minus the synthetic teaching files, which
# must never shape a real benchmark.
BENCHMARK_TICKERS = [
    # ~170 US large and mid caps across every major sector. Wide enough that
    # sector medians are built from real samples rather than a handful, and
    # that the market scan shows a market rather than a shortlist.
    #
    # Edit this list and re-run to change the universe. Tickers that fail are
    # reported and skipped, so a delisting does not break the build.

    # Airlines and transport
    "AAL", "DAL", "UAL", "LUV", "ALK", "JBLU", "UPS", "FDX", "CSX", "UNP",
    "NSC", "ODFL", "CHRW", "EXPD",
    # Autos and suppliers
    "F", "GM", "TSLA", "RIVN", "LCID", "APTV", "BWA", "LEA", "GT", "HOG",
    # Cruise, hotels, restaurants, leisure
    "CCL", "RCL", "NCLH", "MAR", "HLT", "H", "WH", "MCD", "SBUX", "CMG",
    "YUM", "DRI", "DPZ", "WEN", "LVS", "MGM", "WYNN", "CZR",
    # Retail
    "WMT", "TGT", "COST", "HD", "LOW", "M", "KSS", "JWN", "BBY", "GPS",
    "DG", "DLTR", "ROST", "TJX", "ULTA", "FL", "BBWI", "AEO",
    # Media, telecom, entertainment
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "DIS", "WBD", "PARA", "NFLX", "FOXA",
    "LYV", "NYT", "OMC", "IPG",
    # Technology and semis
    "MSFT", "AAPL", "GOOGL", "META", "AMZN", "ORCL", "IBM", "INTC", "AMD",
    "NVDA", "QCOM", "TXN", "MU", "AVGO", "CRM", "ADBE", "NOW", "SNOW",
    "PLTR", "DELL", "HPQ", "HPE", "WDC", "STX", "ZM", "UBER", "LYFT", "DASH",
    # Consumer staples
    "KO", "PEP", "PG", "KHC", "GIS", "K", "CPB", "SJM", "HSY", "KMB", "CL",
    "EL", "MO", "PM", "STZ", "TAP", "MDLZ", "CAG",
    # Healthcare and pharma
    "PFE", "MRK", "JNJ", "ABBV", "BMY", "LLY", "AMGN", "GILD", "BIIB", "CVS",
    "UNH", "CI", "HUM", "MCK", "ABT", "TMO", "DHR", "BAX", "ZBH", "HOLX",
    # Industrials
    "BA", "CAT", "DE", "HON", "GE", "MMM", "LMT", "RTX", "NOC", "GD", "EMR",
    "ETN", "PH", "ITW", "CMI", "PCAR", "SWK", "DOV",
    # Energy and materials
    "XOM", "CVX", "COP", "OXY", "SLB", "HAL", "DVN", "FANG", "MPC", "VLO",
    "PSX", "KMI", "WMB", "OKE", "FCX", "NUE", "DOW", "LYB", "PPG", "SHW",
    "NEM", "MOS", "CF",
    # Utilities and real estate
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED", "PCG",
    "AMT", "PLD", "SPG", "O", "VTR", "WELL", "BXP", "HST",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
    "AXP", "SCHW", "BLK", "BX", "KKR", "APO", "ARES", "CG",

    # --- second tranche: mid caps and wider sector coverage --------------
    # Transport and logistics
    "ALGT", "SKYW", "MATX", "XPO", "SAIA", "WERN", "KNX", "LSTR", "GXO",
    "HUBG", "ARCB",
    # Autos, suppliers, dealers
    "AXL", "ADNT", "DAN", "MOD", "VC", "GPC", "AAP", "ORLY", "AZO", "LAD",
    "AN", "PAG", "KMX", "URI",
    # Travel, leisure, restaurants
    "EXPE", "BKNG", "ABNB", "TNL", "HGV", "VAC", "PLNT", "FUN", "CHDN",
    "DKNG", "PENN", "BYD", "RRR", "TXRH", "EAT", "CAKE", "BLMN", "JACK",
    "PZZA", "SHAK", "WING", "CBRL",
    # Retail, apparel, e-commerce
    "BURL", "FIVE", "OLLI", "CRI", "LEVI", "PVH", "RL", "VFC", "HBI", "UAA",
    "NKE", "DECK", "CROX", "SKX", "WSM", "RH", "W", "CHWY", "ETSY", "EBAY",
    "SIG", "DKS",
    # Media, telecom, entertainment
    "LUMN", "FYBR", "IRDM", "AMC", "CNK", "IMAX", "ROKU", "SPOT", "WMG",
    "MSGE", "MSGS", "TKO",
    # Technology, software, semis
    "CSCO", "ANET", "JNPR", "MSI", "ZBRA", "KEYS", "TER", "LRCX", "AMAT",
    "KLAC", "ON", "MCHP", "SWKS", "QRVO", "MPWR", "ENTG", "SANM", "FLEX",
    "JBL", "CDW", "NTAP", "PSTG", "BOX", "DBX", "TWLO", "OKTA", "DDOG",
    "MDB", "NET", "ZS", "CRWD", "PANW", "FTNT", "TEAM", "WDAY", "VEEV",
    "HUBS", "DOCU", "PCOR",
    # Food, beverage, household
    "ADM", "BG", "INGR", "DAR", "TSN", "HRL", "POST", "LW", "FLO", "UTZ",
    "SMPL", "CELH", "MNST", "KDP", "COKE", "USFD", "PFGC", "SYY", "CHD",
    "CLX", "ENR", "COTY",
    # Healthcare, pharma, devices, providers
    "VTRS", "TEVA", "JAZZ", "ALKS", "INCY", "EXEL", "HALO", "NBIX", "SRPT",
    "IONS", "BMRN", "UTHR", "OGN", "PRGO", "ELAN", "ZTS", "IDXX", "RMD",
    "STE", "BDX", "SYK", "BSX", "EW", "ISRG", "PODD", "DXCM", "HCA", "THC",
    "UHS", "CYH", "EHC", "SEM", "ACHC", "DVA", "OMI", "CAH", "COR", "MOH",
    "CNC", "ELV",
    # Industrials, aerospace, defence, machinery
    "TXT", "HII", "LDOS", "BAH", "CACI", "SAIC", "KBR", "ACM", "PWR", "MTZ",
    "DY", "FIX", "EME", "AOS", "LII", "TT", "CARR", "JCI", "IR", "XYL",
    "FLS", "PNR", "GGG", "NDSN", "AME", "ROK", "HWM", "SPR", "HEI", "TDG",
    "CW", "ATI", "CRS", "WY",
    # Energy
    "EOG", "HES", "APA", "CTRA", "EQT", "AR", "RRC", "NOV", "FTI", "CHX",
    "TDW", "RIG", "VAL", "HP", "PTEN", "LNG", "TRGP", "ET", "EPD", "PAA",
    # Utilities
    "DTE", "WEC", "ES", "FE", "CMS", "CNP", "NI", "PNW", "AES", "LNT",
    "EVRG", "ATO", "OGE", "POR",
    # Materials, metals, chemicals, packaging
    "X", "CLF", "STLD", "RS", "CMC", "ATKR", "VMC", "MLM", "EXP", "CE",
    "EMN", "ALB", "FMC", "HUN", "OLN", "WLK", "AVNT", "ASH", "IFF", "ECL",
    "APD", "LIN", "SMG", "SEE", "PKG", "IP", "GPK", "SON",
    # Real estate
    "DLR", "EQIX", "PSA", "EXR", "CUBE", "AVB", "EQR", "MAA", "UDR", "ESS",
    "CPT", "INVH", "AMH", "ELS", "SUI", "REG", "FRT", "KIM", "BRX", "MAC",
    "OHI", "MPW", "SBRA", "ARE", "KRC", "HIW", "SLG", "VNO",
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

        # A median that mixes banks with manufacturers is not a benchmark.
        applies = assess(sector, history.industry)
        if not applies.can_rate:
            print("skipped (framework not applicable)")
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
