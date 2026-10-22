#!/usr/bin/env python3
"""
Credit Health & Restructuring Watch Agent -- web dashboard.

Run it with:
    streamlit run app.py

THIS FILE IS A VIEW, NOT A CALCULATOR.

Every number it displays comes from the screener/ package: metrics.py computes
the ratios, signals.py detects the warning signs, scenario.py runs the downside
case, rating.py scores the stress. This file lays them out and labels them.

That separation is what makes the project defensible. The command-line tool
(main.py) and this dashboard produce identical numbers because they call the
same pure functions. You can unit-test the finance without touching the UI, and
you can rebuild the UI without endangering the finance.

The pipeline the dashboard displays, in order:
    Ticker -> Financial Data -> Calculations -> Pattern Detection
           -> Stress Test -> Explanation
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st

from screener import ai, briefing, news
from screener.data_loader import DataLoadError, load_history
from screener.metrics import YearMetrics, compute_all_metrics
from screener.models import FinancialHistory
from screener.altman import (compute_z_score, components,
                             interpretation, is_meaningful_for)
from screener.peers import (PeerCacheUnavailable, compare_to_sector,
                            load_peer_cache)
from screener.narrative import (build_narrative, restructuring_watch,
                                scenario_explanation,
                                structural_caveats)
from screener.rating import (ELEVATED, INSUFFICIENT, LOW, LOW_CEILING,
                             MODERATE, MODERATE_CEILING, rate_stress,
                             rating_trajectory, trajectory_summary)
from screener.scenario import run_ebitda_downside
from screener.signals import evaluate_signals

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

# The browser-tab icon. A drawn mark rather than an emoji; regenerate it with
# `python3 make_favicon.py`. Falls back to an emoji if the file is missing, so
# a fresh clone still runs.
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets", "favicon.png")
PAGE_ICON = _ICON_PATH if os.path.exists(_ICON_PATH) else "\U0001F4C9"

st.set_page_config(
    page_title="Credit Health & Restructuring Watch Agent",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Colours for the three stress ratings. Kept here so the rating logic in
# rating.py stays free of presentation concerns.
RATING_COLORS = {
    LOW: "#1a7f37",       # green
    MODERATE: "#bf8700",  # amber
    ELEVATED: "#b42318",  # red
    INSUFFICIENT: "#6e7781",
}

# ---------------------------------------------------------------------------
# Visual identity
#
# The same type and colour system the hosted page uses, so the live app and the
# static version read as one project. Three typefaces, each with a job:
#
#   IBM Plex Serif  headings -- institutional, report-like, suits credit work
#   IBM Plex Sans   body and interface
#   IBM Plex Mono   every figure, with tabular numerals so digits line up in
#                   columns. This matters more than it sounds: ratios that
#                   don't align are genuinely harder to compare down a page.
#
# Colours come from .streamlit/config.toml for Streamlit's own chrome, and from
# the tokens below for everything this file draws.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Visual identity
#
# The same type and colour system the hosted page uses, so the live app and
# the static version read as one project. Three typefaces, each with a job:
#
#   IBM Plex Serif  headings -- institutional, report-like, suits credit work
#   IBM Plex Sans   body and interface
#   IBM Plex Mono   every figure, with tabular numerals so digits line up in
#                   columns. Ratios that do not align are genuinely harder to
#                   compare down a page.
#
# NOTE ON THE FORMATTING BELOW: Streamlit renders this string as Markdown
# before it reaches the browser, and a blank line inside raw HTML ends the
# HTML block -- everything after it is then printed as visible text. So the
# CSS is one contiguous block with no blank lines, and the fonts are pulled
# in with @import rather than <link> elements.
# ---------------------------------------------------------------------------

# Two palettes. Streamlit 1.50 holds only one theme at a time and exposes no
# CSS variables of its own, so the toggle below overrides both our tokens and
# Streamlit's own chrome. Light is the default: a teacher reading this in
# daylight is the common case, and dark is one click away for a darkened room.
THEMES = {
    "Light": {
        "paper": "#f7f8fa", "surface": "#ffffff", "sunk": "#eef1f5",
        "ink": "#16202e", "ink_soft": "#4a5a6e", "ink_faint": "#76859a",
        "rule": "#d9dfe8", "rule_strong": "#b9c3d1", "steel": "#2a5d8f",
        "scheme": "light",
    },
    "Dark": {
        "paper": "#0e141c", "surface": "#161e29", "sunk": "#1d2733",
        "ink": "#e8edf4", "ink_soft": "#a8b5c6", "ink_faint": "#7c8a9c",
        "rule": "#2a3644", "rule_strong": "#3d4c5e", "steel": "#74aae0",
        "scheme": "dark",
    },
}

FONT_IMPORT = ("@import url('https://fonts.googleapis.com/css2?"
               "family=IBM+Plex+Mono:wght@400;500;600&"
               "family=IBM+Plex+Sans:wght@400;500;600;700&"
               "family=IBM+Plex+Serif:wght@500;600&display=swap');")

# Streamlit renders this string as Markdown before it reaches the browser, and
# a blank line inside raw HTML ends the HTML block -- everything after it would
# then print to the page as visible text. So the CSS stays one contiguous block
# with no blank lines, and the fonts arrive by @import rather than <link>.
CSS_RULES = """html, body, [class*="st-"], .stMarkdown, button, input, textarea, select {
font-family: var(--font-body);
}
/* Streamlit draws its icons as ligature glyphs in a Material font. The rule
above would override that font and print the glyph NAME instead -- the status
tick renders as the literal word "check". Restore the icon font for anything
Streamlit marks as an icon. */
[data-testid*="Icon"], [data-testid*="icon"], .material-icons,
.material-symbols-rounded, span[class*="material"] {
font-family: "Material Symbols Rounded", "Material Icons" !important;
}
.block-container { padding-top: 2.2rem; max-width: 1140px; }
h1, h2, h3 { font-family: var(--font-display) !important; }
h1 { font-weight: 600 !important; letter-spacing: -0.015em; line-height: 1.15 !important; }
h2 { font-weight: 600 !important; }
h3 { font-family: var(--font-body) !important; font-weight: 600 !important; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], .stDataFrame, code, .num {
font-family: var(--font-figure) !important; font-variant-numeric: tabular-nums;
}
[data-testid="stMetricValue"] {
font-size: 1.68rem !important; font-weight: 500 !important; letter-spacing: -0.01em;
}
[data-testid="stMetricLabel"] {
font-size: 0.78rem !important; font-weight: 600 !important;
color: var(--ink-soft) !important; letter-spacing: 0.02em;
}
/* Streamlit truncates metric labels and deltas with an ellipsis when the
column is narrow, which turned "Net Debt / EBITDA" into "Net Debt / ..." and
"+1.81x vs prior year" into "+1.81x vs pri...". Let both wrap instead: two
short lines are readable, half a label is not. */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * ,
[data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
white-space: normal !important; overflow: visible !important;
text-overflow: clip !important; line-height: 1.3 !important;
}
[data-testid="stMetricLabel"] { min-height: 2.1em; display: flex;
align-items: flex-start; }
[data-testid="stMetricDelta"] { font-size: 0.76rem !important; }
[data-testid="stMetric"] {
background: var(--surface); border: 1px solid var(--rule);
border-radius: 4px; padding: 13px 15px 12px;
}
[data-testid="stForm"] {
background: var(--surface); border: 1px solid var(--rule);
border-radius: 5px; padding: 16px 18px;
}
.stTextInput input {
font-family: var(--font-figure) !important; letter-spacing: 0.08em;
text-transform: uppercase; border-radius: 3px !important;
}
.stButton button, [data-testid="stFormSubmitButton"] button {
border-radius: 3px; font-weight: 600; letter-spacing: 0.01em;
}
/* Streamlit truncates button labels with an ellipsis in a narrow column, so
"Analyze Company" became "Analyze Com...". Let the label wrap to two lines
instead and give the button room for it. */
.stButton button p, [data-testid="stFormSubmitButton"] button p,
.stButton button div, [data-testid="stFormSubmitButton"] button div {
white-space: normal !important; overflow: visible !important;
text-overflow: clip !important; line-height: 1.25 !important;
}
[data-testid="stFormSubmitButton"] button { min-height: 2.9rem; height: auto; }
.rating-badge {
padding: 1.15rem 1.3rem; border-radius: 5px; color: #fff;
text-align: center; margin-bottom: 0.45rem;
}
.rating-badge .label {
font-size: 0.7rem; letter-spacing: 0.13em; text-transform: uppercase;
opacity: 0.88; font-weight: 600;
}
.rating-badge .value {
font-family: var(--font-display); font-size: 1.85rem; font-weight: 600;
line-height: 1.2; white-space: nowrap;
}
.metric-note {
font-size: 0.79rem; color: var(--ink-faint); margin-top: -0.35rem;
margin-bottom: 0.95rem; line-height: 1.4;
}
.signal-row { margin-bottom: 0.85rem; line-height: 1.45; }
.signal-name { font-weight: 600; }
.signal-detail { color: var(--ink-soft); font-size: 0.87rem; }
.pipeline {
font-family: var(--font-figure); font-size: 0.72rem; color: var(--ink-soft);
background: var(--surface); border: 1px solid var(--rule);
border-radius: 3px; padding: 9px 11px;
}
hr { border-color: var(--rule) !important; margin: 1.6rem 0 !important; }
[data-testid="stSidebar"] { border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] h3 {
font-family: var(--font-display) !important; font-size: 0.98rem !important;
}
[data-testid="stExpander"] {
border: 1px solid var(--rule) !important; border-radius: 4px !important;
}
[data-testid="stCaptionContainer"] { color: var(--ink-faint); }
@media (prefers-reduced-motion: reduce) {
* { transition: none !important; animation: none !important; }
}"""


def inject_theme(mode: str) -> None:
    """Apply the chosen palette to our components and to Streamlit's chrome."""
    t = THEMES.get(mode, THEMES["Light"])
    tokens = (
        ":root{"
        f"--paper:{t['paper']};--surface:{t['surface']};"
        f"--surface-sunk:{t['sunk']};--ink:{t['ink']};"
        f"--ink-soft:{t['ink_soft']};--ink-faint:{t['ink_faint']};"
        f"--rule:{t['rule']};--rule-strong:{t['rule_strong']};"
        f"--steel:{t['steel']};"
        '--font-display:"IBM Plex Serif",Georgia,serif;'
        '--font-body:"IBM Plex Sans",system-ui,-apple-system,sans-serif;'
        '--font-figure:"IBM Plex Mono",ui-monospace,Menlo,monospace;'
        f"color-scheme:{t['scheme']};"
        "}"
    )
    # Streamlit paints its own surfaces, so the chrome has to be repainted too
    # or the page ends up half dark and half light.
    chrome = (
        "[data-testid='stApp'],[data-testid='stAppViewContainer'],"
        ".stApp{background:var(--paper)!important;color:var(--ink)!important;}"
        "[data-testid='stHeader']{background:transparent!important;}"
        "[data-testid='stSidebar']{background:var(--surface-sunk)!important;}"
        "[data-testid='stSidebar'] *,.stMarkdown,.stMarkdown p,"
        "h1,h2,h3,h4,label,li{color:var(--ink)!important;}"
        "[data-testid='stCaptionContainer'],[data-testid='stCaptionContainer'] *"
        "{color:var(--ink-faint)!important;}"
        "[data-testid='stMetric'],[data-testid='stForm']"
        "{background:var(--surface)!important;border-color:var(--rule)!important;}"
        "[data-testid='stMetricValue']{color:var(--ink)!important;}"
        "[data-testid='stExpander']{background:var(--surface)!important;"
        "border-color:var(--rule)!important;}"
        ".stTextInput input,.stSelectbox div[data-baseweb]{"
        "background:var(--surface)!important;color:var(--ink)!important;"
        "border-color:var(--rule-strong)!important;}"
        ".pipeline{background:var(--surface)!important;}"
    )
    st.markdown("<style>" + FONT_IMPORT + tokens + CSS_RULES + chrome + "</style>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Educational tooltips -- the single source of truth for every definition.
#
# These appear as the small (?) icon beside each metric. Having them in one
# dictionary means the website and the README can never disagree about what a
# metric means.
# ---------------------------------------------------------------------------

METRIC_HELP: Dict[str, str] = {
    "EBITDA":
        "Earnings Before Interest, Taxes, Depreciation and Amortization. "
        "Start from net income and add back interest (which depends on how the "
        "company chose to borrow), taxes (which depend on jurisdiction), and "
        "depreciation and amortization (accounting charges that spread an old "
        "purchase over several years -- no cash leaves the business this "
        "year). What remains approximates the cash the core business generates "
        "before any financing decisions. Its weakness: it ignores the cost of "
        "replacing equipment, which is why free cash flow is also shown.",

    "Debt / EBITDA":
        "Total Debt divided by EBITDA. Read it as: how many years of EBITDA "
        "would it take to repay all the debt? Rough convention: under 2x is "
        "conservative, 2-4x is normal for a leveraged but healthy business, "
        "4-6x is genuinely leveraged, and above 6x is stressed because "
        "refinancing becomes difficult and expensive. These bands vary a lot "
        "by industry -- a regulated utility can carry more than a cyclical "
        "manufacturer.",

    "Net Debt / EBITDA":
        "(Total Debt minus Cash) divided by EBITDA. The same question as "
        "Debt/EBITDA, but giving the company credit for the cash it already "
        "holds, since that cash could repay borrowings tomorrow. Always lower "
        "than or equal to Debt/EBITDA, and generally the more realistic "
        "measure. One caveat an analyst would check: cash trapped in a foreign "
        "subsidiary, or needed for daily operations, cannot actually repay "
        "debt.",

    "Interest Coverage":
        "EBITDA divided by Interest Expense. How many times over can the "
        "company pay this year's interest bill out of this year's operating "
        "earnings? Above 6x is comfortable, 3-6x adequate, 1.5-3x tight, below "
        "1.5x means the company can barely afford its own debt. This is the "
        "most time-critical metric: interest is due on fixed dates, and "
        "missing a payment is an event of default that can let lenders demand "
        "immediate repayment of the whole loan.",

    "Free Cash Flow":
        "Operating Cash Flow minus Capital Expenditure. The cash genuinely "
        "left over after both running the business and maintaining its "
        "equipment. Positive means the company funds itself and can repay debt. "
        "Negative means it must find cash elsewhere every year -- from "
        "reserves, asset sales, or new borrowing. If it borrows, leverage rises "
        "mechanically year after year with no single dramatic event, which is "
        "the most common path into financial distress.",

    "EBITDA Margin":
        "EBITDA divided by Revenue. Operating earnings kept per dollar of "
        "sales. Useful for separating a volume problem from a profitability "
        "problem: if revenue is flat but margin is falling, the company is "
        "selling just as much and keeping less of it. Margin usually moves "
        "before the leverage ratios react.",

    "Revenue Growth":
        "This year's revenue divided by last year's, minus one. The top line. "
        "It matters first because it feeds everything else: falling revenue "
        "flows into falling EBITDA, which raises leverage and lowers coverage. "
        "A company can become more leveraged while borrowing nothing at all, "
        "simply by shrinking.",

    "Leverage":
        "How much debt a company carries relative to its ability to service "
        "it -- never the dollar amount on its own. $5bn of debt is trivial for "
        "a very large company and fatal for a mid-size one, which is why "
        "leverage is always expressed as a ratio.",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_x(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}x"


# Currency symbols for the handful of currencies Yahoo commonly reports in.
# Anything else falls back to the three-letter code, which is always correct if
# slightly less pretty.
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5"}


def fmt_money(value: Optional[float], history: FinancialHistory) -> str:
    """Format a figure compactly, e.g. '-$680m' or '$35.9bn'.

    Metric cards are narrow, and Streamlit truncates anything too long with an
    ellipsis -- which turned "USD 35,930m" into the useless "USD 35,93...".
    Rolling up to billions keeps every realistic figure inside the card while
    staying readable.
    """
    if value is None:
        return "n/a"
    symbol = CURRENCY_SYMBOLS.get(history.currency, history.currency + " ")
    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if history.units == "millions":
        if magnitude >= 1000:
            return f"{sign}{symbol}{magnitude / 1000:,.1f}bn"
        return f"{sign}{symbol}{magnitude:,.0f}m"
    return f"{sign}{symbol}{magnitude:,.0f}"


def md_money(value: Optional[float], history: FinancialHistory) -> str:
    """fmt_money, escaped for Markdown.

    Streamlit renders st.markdown/warning/success/info text as Markdown, where
    a pair of dollar signs delimits LaTeX math. Two currency figures in one
    sentence therefore turn everything between them into mangled italics --
    "$3.6bn falls due against $1.1bn of cash" became an equation. Escaping the
    dollar sign prevents it.

    Use this for money inside prose; use fmt_money for st.metric, which does
    not parse Markdown.
    """
    return fmt_money(value, history).replace("$", r"\$")


def fmt_pct(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def delta_x(latest: Optional[float], prior: Optional[float],
            higher_is_worse: bool = True,
            versus: str = "vs prior year") -> Dict[str, Optional[str]]:
    """Build the small change indicator under a metric card.

    Streamlit colours a positive delta green by default. For leverage, an
    INCREASE is bad news, so we invert the colour there via delta_color.
    Getting this backwards would make a deteriorating company look like it was
    improving, which is exactly the kind of quiet error this project avoids.

    `versus` names the comparison, because the same helper serves two different
    ones: the metric cards compare against the prior fiscal year, while the
    downside scenario compares against the current year's own figure.
    """
    if latest is None or prior is None:
        return {"delta": None, "delta_color": "off"}
    change = latest - prior
    if abs(change) < 0.005:
        return {"delta": "unchanged", "delta_color": "off"}
    return {
        "delta": f"{change:+.2f}x {versus}",
        "delta_color": "inverse" if higher_is_worse else "normal",
    }


# ---------------------------------------------------------------------------
# The analysis bundle
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def peer_benchmark():
    """Load the sector benchmark once per server process.

    cache_resource rather than cache_data: this is a single read-only object
    shared by every visitor, not per-request data. On a shared cloud host that
    means one disk read for the life of the process instead of one per user.

    Returns (cache, error_message). A missing benchmark must not fail the whole
    analysis -- the app simply shows no comparison and explains why.
    """
    try:
        return load_peer_cache(), None
    except PeerCacheUnavailable as exc:
        return None, str(exc)


@st.cache_data(show_spinner=False, ttl=86400, max_entries=200)
def fetch_history(ticker: str, source: str, years: int) -> FinancialHistory:
    """Stage 1, cached for a day.

    Caching is not an optimisation here, it is what keeps the app working.
    Three reasons:

      * Annual financial statements do not change. Re-fetching the same
        company an hour later returns identical numbers.
      * Yahoo Finance rate-limits repeated requests, and does so far more
        aggressively against shared cloud hosts than against a home
        connection. An uncached app on Streamlit Cloud gets throttled quickly.
      * Streamlit re-runs this entire script on every interaction. Without the
        cache, every nudge of the downside slider would trigger a fresh
        network call.

    A 24-hour TTL suits annual data; `max_entries` bounds memory so a long
    session of lookups cannot grow without limit.
    """
    return load_history(ticker, source=source, max_years=years)


def run_agent_workflow(ticker: str, source: str, years: int,
                       use_claude: bool) -> Optional[Dict[str, object]]:
    """Run the pipeline, reporting each step as it actually completes.

    EVERY LINE PRINTED HERE CORRESPONDS TO WORK THAT REALLY RAN, and each one
    is written only after the step it describes has finished. There are no
    artificial delays and no steps that merely claim to be happening.

    That is a deliberate constraint, and worth defending: a progress display
    that pads itself with sleeps is lying about what the program does, and if
    a reader cannot trust the visible part of the tool they have no reason to
    trust the arithmetic underneath it. The honest version runs faster and
    reports less -- which is the correct trade.

    Each line also reports a RESULT (how many years were retrieved, how many
    signals fired), so the display carries information rather than reassurance.
    """
    with st.status(f"Analyzing {ticker.upper()}...", expanded=True) as status:

        # --- Step 1: gather financial data --------------------------------
        try:
            history = fetch_history(ticker, source, years)
        except DataLoadError as exc:
            status.update(label=f"Could not analyze {ticker.upper()}",
                          state="error")
            st.error(str(exc))
            return None

        years_found = len(history.years)
        st.write(f"Gathered financial data — {years_found} fiscal years "
                 f"from {history.source}")

        if years_found < 2:
            status.update(label=f"Not enough history for {ticker.upper()}",
                          state="error")
            st.error(
                f"Only {years_found} fiscal year was returned for "
                f"'{ticker.upper()}'. Trend analysis needs at least two years, "
                "so this company cannot be screened.")
            return None

        # --- Step 2: credit metrics ---------------------------------------
        metrics = compute_all_metrics(history)
        latest = metrics[-1]
        computed = sum(1 for key in ("debt_to_ebitda", "net_debt_to_ebitda",
                                     "interest_coverage", "free_cash_flow",
                                     "ebitda_margin")
                       if getattr(latest, key) is not None)
        st.write(f"Calculated credit metrics — {computed} of 5 computable "
                 f"for {latest.year}")

        # --- Step 3: historical trends ------------------------------------
        signals = evaluate_signals(history, metrics)
        st.write(f"Analyzed historical trends — "
                 f"{history.sorted_years()[0].year} to {latest.year}")

        # --- Step 4: downside scenario ------------------------------------
        all_years = history.sorted_years()
        scenario = run_ebitda_downside(all_years[-1], all_years[-2],
                                       haircut=0.20)
        if scenario.meaningful:
            st.write("Ran 20% EBITDA downside scenario")
        else:
            st.write("Skipped downside scenario — not meaningful when EBITDA "
                     "is negative")

        # --- Step 5: stress signals ---------------------------------------
        fired = sum(1 for sig in signals if sig.status == "fired")
        rating = rate_stress(metrics,
                             [(fy.year, fy.ebitda) for fy in all_years])
        st.write(f"Identified credit signals — {fired} of {len(signals)} "
                 f"triggered")

        # --- Step 6: sector comparison ------------------------------------
        cache, cache_error = peer_benchmark()
        if cache is None:
            peers = {"available": False, "reason": cache_error,
                     "sector": history.sector, "metrics": [],
                     "peerCount": 0, "peerTickers": [], "generated": None}
            st.write("Skipped sector comparison — no benchmark available")
        else:
            peers = compare_to_sector(history.ticker, history.sector,
                                      metrics[-1], cache)
            if peers["available"]:
                st.write(f"Compared against {peers['peerCount']} "
                         f"{history.sector} peers")
            else:
                st.write("Skipped sector comparison — not enough peers")

        trajectory = rating_trajectory(history, compute_all_metrics)
        if len(trajectory) >= 2:
            st.write(f"Traced the rating back to "
                     f"{trajectory[0].year} — {len(trajectory)} point-in-time "
                     "ratings")

        # --- Step 7: summary ----------------------------------------------
        narrative = build_narrative(history, metrics, signals, scenario,
                                    rating)
        analysis: Dict[str, object] = {
            "history": history,
            "metrics": metrics,
            "signals": signals,
            "rating": rating,
            "narrative": narrative,
            "peers": peers,
            "trajectory": trajectory,
        }

        if use_claude:
            try:
                analysis["narrative"] = ai.explain(
                    history, metrics, signals, rating, fallback=narrative)
                st.write("Generated summary — written by Claude")
            except ai.AIUnavailable as exc:
                # Falling back is fine, but the reader must be told, not left
                # to assume they are reading model-written prose.
                st.write("Generated summary — built-in writer")
                st.warning(f"Claude unavailable, so the built-in explanation "
                           f"was used instead. {exc}")
        else:
            st.write("Generated summary")

        status.update(label=f"Analysis complete for {history.ticker} — "
                            f"{rating.rating}",
                      state="complete", expanded=False)
    return analysis


# ---------------------------------------------------------------------------
# Dashboard sections
# ---------------------------------------------------------------------------

def section_header(history: FinancialHistory, metrics: List[YearMetrics]
                   ) -> None:
    """Company name, and a loud banner if the data is not real.

    The heading uses short_name so a long legal name (or the teaching files'
    "(SYNTHETIC...)" marker) does not wrap across three lines. The marker is
    not dropped, though -- it is promoted to a warning banner, because a
    screenshot of this page must never be mistakable for analysis of a real
    company.
    """
    years = history.sorted_years()
    st.markdown(f"## {history.short_name}")

    # Industry is shown when the source provides it. It is descriptive only --
    # no calculation uses it in Version 1 -- but it is the context a reader
    # needs, because the same leverage means different things in different
    # industries.
    bits = [f"Ticker **{history.ticker}**"]
    if history.industry:
        bits.append(f"{history.industry}"
                    + (f" ({history.sector})" if history.sector else ""))
    elif history.sector:
        bits.append(history.sector)
    bits += [f"fiscal years {years[0].year}–{years[-1].year}",
             f"figures in {history.currency} {history.units}",
             f"source: {history.source}"]
    st.caption(" · ".join(bits))

    if "SYNTHETIC" in history.company_name.upper():
        st.warning(
            "**Synthetic teaching data.** These figures were invented to "
            "demonstrate the tool and describe no real company. Switch the "
            "sidebar to Yahoo Finance to analyze a real ticker.")


def section_rating(analysis: Dict[str, object]) -> None:
    """Section 4 of the spec: the prominent stress indicator with reasons."""
    rating = analysis["rating"]
    narrative = analysis["narrative"]
    color = RATING_COLORS.get(rating.rating, "#6e7781")

    left, right = st.columns([1.15, 2], gap="large")
    with left:
        st.markdown(
            f"""<div class="rating-badge" style="background:{color}">
                  <div class="label">Credit Stress</div>
                  <div class="value">{rating.rating.replace(' Stress', '')}</div>
                </div>""",
            unsafe_allow_html=True)
        if rating.ratio is not None:
            st.caption(f"{rating.score} of {rating.max_score} stress points "
                       f"({rating.ratio:.0%}) · {rating.assessed_count} of 5 "
                       "factors assessed")
    with right:
        st.markdown(f"**{narrative.headline}**")
        st.markdown(f"#### Why {rating.rating.replace(' Stress', '')}?")
        for reason in narrative.rating_reasons:
            st.markdown(f"- {reason}")

    if "LOW CONFIDENCE" in rating.confidence_note:
        st.warning(rating.confidence_note)

    # Caveats go directly under the rating, before the metric cards. A reader
    # must meet the warning before they meet the number it applies to.
    for title, explanation in structural_caveats(analysis["history"],
                                                 analysis["metrics"]):
        st.error(f"**{title}**")
        with st.expander("Why, and what an analyst does instead"):
            st.write(explanation)

    points = analysis.get("trajectory") or []
    if len(points) >= 2:
        st.markdown("#### How the rating got here")
        st.caption("The rating as it stood each year. No hindsight: the "
                   "2023 point sees nothing after 2023.")
        st.altair_chart(
            rating_trajectory_chart(points, analysis["history"]),
            use_container_width=True)
        st.caption(trajectory_summary(points))

    with st.expander("How this rating is calculated (every threshold)"):
        st.markdown(
            "Five factors are scored against fixed, published thresholds. The "
            "points are summed and divided by the maximum that could actually "
            "be assessed, so a company with patchy disclosure is not flattered "
            "by the gaps.\n\n"
            "**Below 30% = Low · 30–60% = Moderate · above 60% = Elevated**\n\n"
            "There is no machine-learning model here, deliberately. Every "
            "point traces to one stated threshold, so the rating can be "
            "explained and defended rather than merely reported.")
        rows = [{
            "Factor": f.name,
            "Points": ("not assessed" if f.points is None
                       else f"{f.points} / {f.max_points}"),
            "What the data showed": f.observation,
            "Scale used": f.threshold_note,
        } for f in rating.factors]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     use_container_width=True)


def section_altman(analysis: Dict[str, object]) -> None:
    """A published second opinion, shown beside our own rating.

    Deliberately placed AFTER the rating rather than beside it: this is a
    cross-check on a conclusion already reached, not an input to it. Nothing
    in rating.py consults the Z-score.
    """
    history = analysis["history"]
    rating = analysis["rating"]
    years = history.sorted_years()

    st.markdown("### Second opinion: Altman Z''-score")

    ok, why_not = is_meaningful_for(history.sector)
    if not ok:
        st.info(why_not)
        return

    z = compute_z_score(years[-1])
    st.caption(
        "Our rating asks whether the company can keep paying. Altman's asks "
        "whether the balance sheet can absorb losses. Published 1968.")

    if not z.available:
        st.info(z.reason)
        return

    zone_colour = {"Safe zone": LOW, "Grey zone": MODERATE,
                   "Distress zone": ELEVATED}.get(z.zone, MODERATE)
    left, right = st.columns([1.15, 2], gap="large")
    with left:
        st.markdown(
            f"""<div class="rating-badge" style="background:{RATING_COLORS[zone_colour]}">
                  <div class="label">Altman Z&apos;&apos;</div>
                  <div class="value">{z.score:.2f}</div>
                </div>""", unsafe_allow_html=True)
        st.caption(f"{z.zone} · thresholds 1.1 and 2.6")
    with right:
        # Whether the two methods agree is the most useful line on the page,
        # so it leads.
        ours_stressed = rating.rating in (MODERATE, ELEVATED)
        z_stressed = z.zone != "Safe zone"
        if ours_stressed == z_stressed:
            st.success(
                f"**The two measures agree.** Our rating says "
                f"{rating.rating.lower()} and the Z-score puts the company in "
                f"the {z.zone.lower()}. Two different methods reaching the "
                "same view is more reassuring than either alone.")
        else:
            st.warning(
                f"**The two measures disagree.** Our rating says "
                f"{rating.rating.lower()}, while the Z-score puts the company "
                f"in the {z.zone.lower()}. They measure different things, so "
                "this is information rather than an error — one is reading "
                "debt service, the other the balance sheet. Worth "
                "understanding which picture fits this company better.")
        st.write(interpretation(z))

    with st.expander("How this score is built (every term)"):
        st.markdown(
            "**Z'' = 6.56·X₁ + 3.26·X₂ + 6.72·X₃ + 1.05·X₄**\n\n"
            "The coefficients are Altman's published values; nothing here was "
            "fitted by this project. That is the point of using an outside "
            "model.")
        rows = [{
            "Term": c["label"],
            "Ratio": f"{c['ratio']:.3f}",
            "Weight": f"{c['weight']:.2f}",
            "Contribution": f"{c['contribution']:+.2f}",
            "What it measures": c["explanation"],
        } for c in components(z)]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     use_container_width=True)
        st.caption(
            "This uses the Z'' variant, which drops the original formula's "
            "sales-to-assets term and uses book rather than market equity. "
            "That makes it usable across industries and without share-price "
            "data; the original 1968 Z is really only valid for manufacturers.")


def section_metrics(analysis: Dict[str, object]) -> None:
    """Section 3 of the spec: the four big metric cards, with tooltips."""
    history = analysis["history"]
    metrics: List[YearMetrics] = analysis["metrics"]
    latest = metrics[-1]
    prior = metrics[-2] if len(metrics) >= 2 else None

    st.markdown(f"### Key credit metrics — fiscal year {latest.year}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Net Debt / EBITDA", fmt_x(latest.net_debt_to_ebitda),
                  help=METRIC_HELP["Net Debt / EBITDA"],
                  **delta_x(latest.net_debt_to_ebitda,
                            prior.net_debt_to_ebitda if prior else None))
        st.markdown('<div class="metric-note">Net debt (after cash) relative '
                    'to annual EBITDA.</div>', unsafe_allow_html=True)
    with c2:
        st.metric("Debt / EBITDA", fmt_x(latest.debt_to_ebitda),
                  help=METRIC_HELP["Debt / EBITDA"],
                  **delta_x(latest.debt_to_ebitda,
                            prior.debt_to_ebitda if prior else None))
        st.markdown('<div class="metric-note">Years of EBITDA needed to repay '
                    'all borrowings.</div>', unsafe_allow_html=True)
    with c3:
        st.metric("Interest Coverage", fmt_x(latest.interest_coverage),
                  help=METRIC_HELP["Interest Coverage"],
                  **delta_x(latest.interest_coverage,
                            prior.interest_coverage if prior else None,
                            higher_is_worse=False))
        st.markdown('<div class="metric-note">Times over EBITDA covers the '
                    'interest bill.</div>', unsafe_allow_html=True)
    with c4:
        st.metric("Free Cash Flow", fmt_money(latest.free_cash_flow, history),
                  help=METRIC_HELP["Free Cash Flow"])
        st.markdown('<div class="metric-note">Operating cash flow minus '
                    'capex: cash left over.</div>', unsafe_allow_html=True)

    # Any blank card gets its reason stated, so "n/a" is never mysterious.
    for key, label in [("net_debt_to_ebitda", "Net Debt / EBITDA"),
                       ("debt_to_ebitda", "Debt / EBITDA"),
                       ("interest_coverage", "Interest Coverage"),
                       ("free_cash_flow", "Free Cash Flow")]:
        if getattr(latest, key) is None and key in latest.reasons:
            st.caption(f"**{label}** shows n/a: {latest.reasons[key]}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("EBITDA margin", fmt_pct(latest.ebitda_margin),
                  help=METRIC_HELP["EBITDA Margin"])
    with c2:
        st.metric("Revenue growth", fmt_pct(latest.revenue_growth, signed=True),
                  help=METRIC_HELP["Revenue Growth"])
    with c3:
        st.metric("Net debt", fmt_money(latest.net_debt, history),
                  help="Total debt minus cash. Can be negative, which means "
                       "the company holds more cash than debt -- a net cash "
                       "position, and a strong one.")

    with st.expander("What do these metrics mean? (full definitions)"):
        for term in ("EBITDA", "Leverage", "Debt / EBITDA",
                     "Net Debt / EBITDA", "Interest Coverage",
                     "Free Cash Flow", "EBITDA Margin", "Revenue Growth"):
            st.markdown(f"**{term}** — {METRIC_HELP[term]}")
            st.write("")


def section_peers(analysis: Dict[str, object]) -> None:
    """Sector comparison: is this company's leverage normal for its industry?

    This is the answer to the biggest weakness of the rating in Section 6 of
    the report. Every threshold there is a general convention that cannot tell
    a regulated utility from a cyclical manufacturer. A sector median can.
    """
    peers = analysis.get("peers") or {}
    history = analysis["history"]

    st.markdown("### Industry comparison")
    st.caption("5x leverage is normal for a utility and alarming for a "
               "miner. Here is how this company sits against its sector.")

    if not peers.get("available"):
        st.info(peers.get("reason") or "No sector comparison is available.")
        return

    rows = peers["metrics"]
    cols = st.columns(len(rows))
    for col, m in zip(cols, rows):
        with col:
            if m["companyValue"] is None or m["peerMedian"] is None:
                st.metric(m["label"], "n/a")
                st.caption(m["sentence"])
                continue

            is_pct = m["key"] == "ebitda_margin"
            fmt = (lambda v: f"{v:.1%}") if is_pct else (lambda v: f"{v:.2f}x")
            gap = m["companyValue"] - m["peerMedian"]
            worse = gap > 0 if m["higherIsWorse"] else gap < 0

            st.metric(
                m["label"], fmt(m["companyValue"]),
                delta=f"{'+' if gap > 0 else ''}{fmt(gap).lstrip('+')} vs median",
                # Streamlit colours a positive delta green by default. For
                # leverage, being above the median is bad news, so the colour
                # is inverted to match the finance rather than the arithmetic.
                delta_color="inverse" if m["higherIsWorse"] else "normal",
                help=f"Sector median: {fmt(m['peerMedian'])}. "
                     f"{'Higher' if m['higherIsWorse'] else 'Lower'} than the "
                     "median is worse for this metric.")
            st.caption(
                f"{'Worse' if worse else 'Better'} than the median · "
                f"{m['percentile']:.0f}th percentile of {m['peersUsed']} peers"
                + (f" · {m['peersDropped']} excluded (not computable)"
                   if m["peersDropped"] else ""))

    st.caption(
        f"Compared against {peers['peerCount']} {peers['sector']} companies: "
        f"{', '.join(peers['peerTickers'])}.")

    with st.expander("How this comparison is built, and what it cannot do"):
        st.markdown(
            "**Medians, not averages.** Credit ratios carry severe outliers — "
            "one company with near-zero EBITDA produces a reading in the "
            "hundreds, which would destroy an average. Ford sits at roughly "
            "39x for exactly that reason, and a median absorbs it without "
            "distortion.\n\n"
            "**A company is never its own peer.** Including it would pull the "
            "median toward the very value being judged against it.\n\n"
            "**Uncomputable values are dropped, not zeroed.** A peer whose "
            "leverage is unavailable because EBITDA is negative is excluded "
            "from the median rather than counted as zero, and the number "
            "excluded is shown above.\n\n"
            "**A minimum of four peers is required.** Below that the "
            "comparison is withheld, because a median built from two "
            "companies is an anecdote rather than a benchmark.")
        st.markdown(
            "**Two limits.** The benchmark groups by *broad sector* rather "
            "than narrow industry, because narrow industry groups in a set "
            "this size are too small to clear the four-peer minimum — so an "
            "airline is compared against other industrials, including Boeing "
            "and Caterpillar. And the benchmark is a snapshot taken when it "
            "was last rebuilt, while the company being analysed is live.")
        if peers.get("generated"):
            st.caption(f"Benchmark last rebuilt: {peers['generated']} "
                       "(`python3 build_peer_cache.py` to refresh).")


def section_explanation(analysis: Dict[str, object]) -> None:
    """Section 6 of the spec: the prose explanation."""
    narrative = analysis["narrative"]
    st.markdown("### What is happening?")
    st.write(narrative.what_is_happening)
    st.markdown("#### Why this matters")
    st.write(narrative.why_it_matters)

    if narrative.mode == "claude":
        st.caption("Explanation written by Claude from the figures computed "
                   "above. Claude received only those computed figures and was "
                   "instructed to introduce no numbers of its own.")
    else:
        st.caption("Explanation assembled by Python from the computed figures "
                   "(template mode — deterministic, no language model "
                   "involved). Enable Claude in the sidebar for a "
                   "model-written version.")


# ---------------------------------------------------------------------------
# Distinctive charts
# ---------------------------------------------------------------------------

# The rating bands, as fractions of the maximum assessable score. These are
# the same cut-offs rating.py uses; drawing them means the rating logic is
# visible in the picture rather than asserted in a table elsewhere.
BAND_BOUNDS = [(0.0, LOW_CEILING, "Low"),
               (LOW_CEILING, MODERATE_CEILING, "Moderate"),
               (MODERATE_CEILING, 1.0, "Elevated")]


def rating_trajectory_chart(points: List, history: FinancialHistory) -> alt.Chart:
    """The rating as it stood at the end of each year, over shaded bands.

    A single rating says where a company stands; this says when it got there,
    which is often the more useful fact. Each point is computed from a
    truncated history, so it is a genuine point-in-time rating rather than
    hindsight.
    """
    frame = pd.DataFrame([{
        "Year": str(p.year),
        "Score": (p.ratio or 0) * 100,
        "Rating": p.rating.replace(" Stress", ""),
        "Detail": f"{p.score} of {p.max_score} points",
    } for p in points])

    bands = pd.DataFrame([
        {"lo": lo * 100, "hi": hi * 100, "Band": name}
        for lo, hi, name in BAND_BOUNDS])

    background = (
        alt.Chart(bands)
        .mark_rect(opacity=0.14)
        .encode(
            y=alt.Y("lo:Q", title="Stress score (% of assessable maximum)",
                    scale=alt.Scale(domain=[0, 100])),
            y2="hi:Q",
            color=alt.Color("Band:N",
                            scale=alt.Scale(domain=["Low", "Moderate", "Elevated"],
                                            range=["#1a7f37", "#bf8700", "#b42318"]),
                            legend=None))
    )
    line = (
        alt.Chart(frame)
        .mark_line(point=alt.OverlayMarkDef(size=90, filled=True),
                   strokeWidth=3, color="#16202e", interpolate="monotone")
        .encode(
            x=alt.X("Year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Score:Q", scale=alt.Scale(domain=[0, 100])),
            tooltip=["Year", "Rating", "Detail",
                     alt.Tooltip("Score:Q", format=".0f", title="Score %")])
    )
    return (background + line).properties(height=250)


def leverage_band_chart(frame: pd.DataFrame) -> alt.Chart:
    """Leverage over the conventional credit bands.

    The bands are the same thresholds the rating scores against, so the line
    crossing into red is the rating logic made visible.
    """
    usable = frame[["Year", "Net Debt / EBITDA"]].dropna()
    if usable.empty:
        return None
    top = max(float(usable["Net Debt / EBITDA"].max()) * 1.15, 7.0)

    bands = pd.DataFrame([
        {"lo": 0, "hi": 2, "Band": "Conservative"},
        {"lo": 2, "hi": 4, "Band": "Normal"},
        {"lo": 4, "hi": 6, "Band": "Leveraged"},
        {"lo": 6, "hi": top, "Band": "Stressed"},
    ])
    background = (
        alt.Chart(bands).mark_rect(opacity=0.16).encode(
            y=alt.Y("lo:Q", title="Net Debt / EBITDA (x)",
                    scale=alt.Scale(domain=[0, top])),
            y2="hi:Q",
            color=alt.Color(
                "Band:N",
                scale=alt.Scale(
                    domain=["Conservative", "Normal", "Leveraged", "Stressed"],
                    range=["#1a7f37", "#7aa63f", "#e8a33d", "#b42318"]),
                legend=alt.Legend(title=None, orient="bottom")))
    )
    line = (
        alt.Chart(usable)
        .mark_line(point=alt.OverlayMarkDef(size=70, filled=True),
                   strokeWidth=3, color="#16202e")
        .encode(x=alt.X("Year:N", title="Year", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Net Debt / EBITDA:Q", scale=alt.Scale(domain=[0, top])),
                tooltip=["Year",
                         alt.Tooltip("Net Debt / EBITDA:Q", format=".2f")])
    )
    return (background + line).properties(height=260)


def maturity_wall_chart(schedule, cash: Optional[float],
                        history: FinancialHistory) -> alt.Chart:
    """Debt coming due by year, with cash drawn across it.

    The standard credit picture, and the one thing leverage cannot show: a
    company fails when it misses a payment on a date. The cash line is what
    makes the near bars meaningful -- a tall first bar above the line is the
    shape that starts a refinancing conversation.
    """
    rows = [{"Bucket": b.label, "Amount": b.amount, "Order": i}
            for i, b in enumerate(schedule.buckets) if b.amount is not None]
    if not rows:
        return None
    frame = pd.DataFrame(rows)

    # The nearest rung is the one that matters most, so it is coloured apart.
    frame["Near"] = ["Due within 1 year" if r["Order"] == 0 else "Later"
                     for r in rows]

    bars = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Bucket:N", sort=alt.EncodingSortField("Order"),
                    title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Amount:Q",
                    title=f"{history.currency} {history.units}"),
            color=alt.Color(
                "Near:N",
                scale=alt.Scale(domain=["Due within 1 year", "Later"],
                                range=["#b42318", "#2a5d8f"]),
                legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Bucket", alt.Tooltip("Amount:Q", format=",.0f")])
    )
    layers = [bars]
    if cash is not None:
        cash_line = (
            alt.Chart(pd.DataFrame([{"Cash": cash}]))
            .mark_rule(strokeDash=[6, 4], strokeWidth=2, color="#1a7f37")
            .encode(y="Cash:Q",
                    tooltip=[alt.Tooltip("Cash:Q", format=",.0f",
                                         title="Cash on hand")])
        )
        layers.append(cash_line)
    return alt.layer(*layers).properties(height=260)


def trend_line_chart(frame: pd.DataFrame, columns: List[str],
                     colors: List[str], y_title: str) -> alt.Chart:
    """A multi-series line chart over fiscal years.

    Built with Altair rather than st.line_chart for two reasons: st.line_chart
    picked its own y-axis domain and flattened the series into an unreadable
    sliver, and this way the colour of each series is fixed rather than
    assigned automatically.

    The y-axis INCLUDES ZERO deliberately (scale zero=True). A truncated axis
    makes a small change look dramatic, which is the oldest trick in chart
    design and the wrong habit for a finance tool. On a zero-based axis a
    leverage move from 2x to 6x looks like what it is -- large -- while a move
    from 8.7x to 9.7x looks like what it is: proportionally modest.
    """
    long = (frame[["Year"] + columns]
            .melt(id_vars="Year", value_vars=columns,
                  var_name="Metric", value_name="Value")
            .dropna(subset=["Value"]))
    return (
        alt.Chart(long)
        .mark_line(point=True, strokeWidth=2.5)
        .encode(
            x=alt.X("Year:N", title="Year",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Value:Q", title=y_title,
                    scale=alt.Scale(zero=True)),
            color=alt.Color(
                "Metric:N",
                scale=alt.Scale(domain=columns, range=colors),
                # One series needs no legend: the heading above already names
                # it, and an extra swatch just adds clutter.
                legend=(alt.Legend(title=None, orient="bottom")
                        if len(columns) > 1 else None)),
            tooltip=[alt.Tooltip("Year:N"), alt.Tooltip("Metric:N"),
                     alt.Tooltip("Value:Q", format=".2f")],
        )
        .properties(height=250)
    )


def section_trends(analysis: Dict[str, object]) -> None:
    """Section 5 of the spec: the three historical charts."""
    history = analysis["history"]
    metrics: List[YearMetrics] = analysis["metrics"]
    st.markdown("### Historical trends")
    st.caption("Direction matters more than any single year.")

    # Year as a string so the axis reads "2024", not "2,024".
    frame = pd.DataFrame({
        "Year": [str(m.year) for m in metrics],
        "Net Debt / EBITDA": [m.net_debt_to_ebitda for m in metrics],
        "Debt / EBITDA": [m.debt_to_ebitda for m in metrics],
        "Interest Coverage": [m.interest_coverage for m in metrics],
        "Free Cash Flow": [m.free_cash_flow for m in metrics],
    })

    st.markdown("**Leverage** — higher is worse")
    if frame["Net Debt / EBITDA"].notna().any():
        banded = leverage_band_chart(frame)
        if banded is not None:
            st.altair_chart(banded, use_container_width=True)
            note = ("The shaded bands are the same thresholds the rating "
                    "scores against, so the line crossing into red is the "
                    "rating logic made visible rather than described.")
            # One extreme year compresses every band below it. The axis is
            # left honest and the reason is stated, rather than clipping the
            # outlier out of sight.
            peak = frame["Net Debt / EBITDA"].max()
            if pd.notna(peak) and peak > 15:
                note += (f" The axis reaches {peak:.0f}x because of a single "
                         "extreme year, which compresses the lower bands.")
            st.caption(note)
        with st.expander("Show gross Debt/EBITDA alongside net"):
            st.altair_chart(
                trend_line_chart(frame,
                                 ["Net Debt / EBITDA", "Debt / EBITDA"],
                                 ["#b42318", "#e8a33d"], "Multiple (x)"),
                use_container_width=True)
    else:
        st.info("Leverage could not be charted: net debt or EBITDA "
                "unavailable for every year.")

    st.markdown("**Interest coverage** — lower is worse")
    if frame["Interest Coverage"].notna().any():
        st.altair_chart(
            trend_line_chart(frame, ["Interest Coverage"], ["#1f6feb"],
                             "Coverage (x)"),
            use_container_width=True)
    else:
        st.info("Interest coverage could not be charted: EBITDA or interest "
                "expense unavailable for every year.")

    st.markdown("**Free cash flow** — below zero means the business did not "
                "fund itself")
    if frame["Free Cash Flow"].notna().any():
        # Built with Altair rather than st.bar_chart so each bar can be
        # coloured by its own sign. A negative free-cash-flow year drawn in
        # green reads as good news at a glance, which is precisely backwards:
        # it is the year the business did not fund itself.
        fcf = frame[["Year", "Free Cash Flow"]].dropna().copy()
        fcf["Sign"] = ["Negative" if v < 0 else "Positive"
                       for v in fcf["Free Cash Flow"]]
        chart = (
            alt.Chart(fcf)
            .mark_bar()
            .encode(
                x=alt.X("Year:N", title="Year"),
                y=alt.Y("Free Cash Flow:Q",
                        title=f"{history.currency} {history.units}"),
                color=alt.Color(
                    "Sign:N",
                    scale=alt.Scale(domain=["Positive", "Negative"],
                                    range=["#1a7f37", "#b42318"]),
                    legend=alt.Legend(title=None, orient="bottom")),
                tooltip=["Year", "Free Cash Flow", "Sign"],
            )
            .properties(height=250)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Free cash flow could not be charted: operating cash flow or "
                "capex unavailable for every year.")

    with st.expander("See the underlying figures"):
        years = {fy.year: fy for fy in history.sorted_years()}
        table = pd.DataFrame([{
            "Year": m.year,
            "Revenue": years[m.year].revenue,
            "EBITDA": years[m.year].ebitda,
            "EBITDA margin": fmt_pct(m.ebitda_margin),
            "Total debt": years[m.year].total_debt,
            "Cash": years[m.year].cash,
            "Debt/EBITDA": fmt_x(m.debt_to_ebitda),
            "Net Debt/EBITDA": fmt_x(m.net_debt_to_ebitda),
            "Coverage": fmt_x(m.interest_coverage),
            "Free cash flow": m.free_cash_flow,
        } for m in metrics])
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.caption(f"Figures in {history.currency} {history.units}. "
                   "Blank cells are data the source did not provide; they are "
                   "never filled in with estimates.")


def signal_icon(name: str, status: str, analysis: Dict[str, object]) -> str:
    """Pick the dot colour for a warning sign.

    Red is reserved for a fired signal whose latest reading is at a level that
    would genuinely worry a lender. Everything else that fired is amber.

    This is PRESENTATION ONLY -- the colour has no effect on the stress rating,
    which is computed in rating.py from its own stated thresholds.
    """
    if status == "unknown":
        return "⚪"
    if status == "clear":
        return "🟢"

    latest = analysis["metrics"][-1]
    critical = (
        (name == "Negative free cash flow"),
        (name == "Interest coverage decreasing"
         and latest.interest_coverage is not None
         and latest.interest_coverage < 1.5),
        (name == "Leverage (Net Debt/EBITDA) increasing"
         and latest.net_debt_to_ebitda is not None
         and latest.net_debt_to_ebitda > 6.0),
    )
    return "🔴" if any(critical) else "🟠"


def section_signals(analysis: Dict[str, object]) -> None:
    """Section 7 of the spec: the warning signs."""
    signals = analysis["signals"]
    fired = [s for s in signals if s.status == "fired"]
    clear = [s for s in signals if s.status == "clear"]
    unknown = [s for s in signals if s.status == "unknown"]

    st.markdown("### Key credit signals")
    st.caption(f"{len(fired)} of {len(signals)} triggered. One signal is a "
               "question, not an answer. Look for several pointing the same "
               "way.")

    for group, heading in ((fired, None), (clear, "Not a current concern"),
                           (unknown, "Could not assess")):
        if not group:
            continue
        if heading:
            st.markdown(f"**{heading}**")
        for s in group:
            icon = signal_icon(s.name, s.status, analysis)
            st.markdown(
                f'<div class="signal-row">{icon} '
                f'<span class="signal-name">{s.name}</span><br>'
                f'<span class="signal-detail">{s.detail}</span></div>',
                unsafe_allow_html=True)
            if s.status == "fired":
                with st.expander(f"Why this matters — {s.name}", expanded=False):
                    st.write(s.why_it_matters)

    if unknown:
        st.caption("A signal shown as ‘could not assess’ is **not** the same "
                   "as ‘no problem’. It means the data needed to check it was "
                   "unavailable.")


def section_scenario(analysis: Dict[str, object]) -> None:
    """Section 8 of the spec: the interactive stress test.

    The slider is the best thing in the whole project to demonstrate live. Move
    it in front of your class and watch leverage rise faster than the earnings
    decline that caused it.
    """
    history = analysis["history"]
    years = history.sorted_years()
    latest, prior = years[-1], years[-2] if len(years) >= 2 else None

    st.markdown("### Downside stress test")
    st.caption("Debt, cash and interest held constant. Only earnings move.")

    pct = st.slider("EBITDA decline", min_value=0, max_value=50, value=20,
                    step=5, format="%d%%",
                    help="A 20% decline is roughly a normal cyclical downturn "
                         "for an average business — bad, but not "
                         "catastrophic. It is a deliberately plain figure you "
                         "can justify in one sentence.")

    # Recomputed in Python on every slider move -- same function the CLI and
    # the unit tests use. The dashboard never does this arithmetic itself.
    result = run_ebitda_downside(latest, prior, haircut=pct / 100.0)

    if not result.meaningful:
        st.info(result.note)
        return

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Current**")
        st.metric("EBITDA", fmt_money(result.base_ebitda, history))
        st.metric("Net Debt / EBITDA", fmt_x(result.base.net_debt_to_ebitda))
        st.metric("Debt / EBITDA", fmt_x(result.base.debt_to_ebitda))
        st.metric("Interest Coverage", fmt_x(result.base.interest_coverage))
    with right:
        st.markdown(f"**EBITDA falls {pct}%**")
        st.metric("EBITDA", fmt_money(result.stressed_ebitda, history),
                  delta=(None if pct == 0 else f"-{pct}%"),
                  delta_color="inverse")
        st.metric("Net Debt / EBITDA",
                  fmt_x(result.stressed.net_debt_to_ebitda),
                  **delta_x(result.stressed.net_debt_to_ebitda,
                            result.base.net_debt_to_ebitda,
                            versus="vs current"))
        st.metric("Debt / EBITDA", fmt_x(result.stressed.debt_to_ebitda),
                  **delta_x(result.stressed.debt_to_ebitda,
                            result.base.debt_to_ebitda,
                            versus="vs current"))
        st.metric("Interest Coverage",
                  fmt_x(result.stressed.interest_coverage),
                  **delta_x(result.stressed.interest_coverage,
                            result.base.interest_coverage,
                            higher_is_worse=False, versus="vs current"))

    # The explanation is regenerated for the current slider value, so the prose
    # always matches the numbers on screen.
    st.info(scenario_explanation(result))


def section_maturities(analysis: Dict[str, object]) -> None:
    """When the debt actually comes due.

    This answers what leverage structurally cannot. Companies fail on a date,
    not at a threshold, and until now the tool was blind to timing entirely --
    the limitation its own report named first.
    """
    history = analysis["history"]
    schedule = history.maturities
    years = history.sorted_years()
    cash = years[-1].cash if years else None

    st.markdown("### Debt maturity wall")

    if schedule is None:
        st.info(
            "No maturity schedule is available for this company. The figures "
            "come from the long-term debt note of the 10-K, which only the "
            "**SEC EDGAR** source provides — switch the data source in the "
            "sidebar to see it. Some filers also leave the schedule untagged.")
        return

    st.caption(
        f"Principal due by year, from the {schedule.as_of_year} filing. "
        "Dashed line is cash on hand.")

    chart = maturity_wall_chart(schedule, cash, history)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)

    near = schedule.due_within_one_year
    cols = st.columns(3)
    with cols[0]:
        st.metric("Due within 1 year", fmt_money(near, history))
    with cols[1]:
        st.metric("Cash on hand", fmt_money(cash, history))
    with cols[2]:
        st.metric("Total scheduled", fmt_money(schedule.total, history))

    # The comparison that matters, stated rather than left to the reader.
    if near is not None and cash is not None:
        if near > cash:
            st.warning(
                f"**{md_money(near, history)} falls due within twelve months "
                f"against {md_money(cash, history)} of cash.** The shortfall "
                "has to come from operating cash flow, asset sales, or "
                "refinancing. Whether refinancing is available, and at what "
                "cost, is the question this raises.")
        else:
            st.success(
                f"**{md_money(near, history)} falls due within twelve months, "
                f"covered by {md_money(cash, history)} of cash.** The nearest "
                "maturity does not depend on refinancing.")

    missing = [b.label for b in schedule.buckets if b.amount is None]
    if missing:
        st.caption(
            "Not tagged in the filing: " + ", ".join(missing) +
            ". Those rungs are left out rather than shown as zero, so the "
            "total above understates the full schedule.")


def section_restructuring_watch(analysis: Dict[str, object]) -> None:
    """The Restructuring Watch section.

    This is explicitly NOT an attempt to design a restructuring, and it makes
    no prediction about bankruptcy. It names the questions the metrics raise
    but cannot answer -- the honest handoff from a screen to real analysis.
    """
    rating = analysis["rating"]
    headline, items = restructuring_watch(
        rating, analysis["signals"], analysis["metrics"])

    st.markdown("### Restructuring watch")

    if rating.rating == LOW:
        st.success(headline)
    elif rating.rating == INSUFFICIENT:
        st.warning(headline)
    else:
        st.warning(headline)

    for area, why in items:
        with st.expander(area):
            st.write(why)

    st.caption(
        "This section identifies areas to investigate. It does not design a "
        "restructuring and makes no prediction about default or bankruptcy — "
        "neither is supportable from the figures screened here.")


def section_limitations(analysis: Dict[str, object]) -> None:
    """Section 10 of the spec: data sources and limitations."""
    history = analysis["history"]
    st.markdown("### Data sources and limitations")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Where the data came from**")
        st.write(f"Source: {history.source}")
        st.caption(history.provenance)
        if history.notes:
            st.markdown("**How some figures were constructed**")
            for key, note in sorted(history.notes.items()):
                st.caption(f"*{key}*: {note}")

        missing = history.latest().missing_fields()
        if missing:
            st.warning(
                f"Missing in the latest year: {', '.join(missing)}. Metrics "
                "depending on these show n/a rather than an estimate.")

    with right:
        st.markdown("**What this tool cannot see**")
        st.markdown(
            "- **Debt maturity dates** — the most important gap. 6x leverage "
            "with nothing due for five years is survivable; the same leverage "
            "with a large maturity next year is urgent.\n"
            "- **Covenant levels** — a breach can let lenders demand "
            "immediate repayment, which is often what starts a restructuring.\n"
            "- **Industry context** — thresholds here are general conventions. "
            "5x is routine for a utility and alarming for a cyclical "
            "manufacturer.\n"
            "- **EBITDA quality** — reported figures may include generous "
            "add-backs, and every ratio rests on that denominator.\n"
            "- **Undrawn credit facilities** — often the difference between a "
            "problem and a crisis.\n"
            "- **Cyclical versus structural decline** — the judgement that "
            "matters most, which no ratio answers.\n"
            "- **Annual data only** — a company can deteriorate fast inside a "
            "fiscal year.")

    st.caption(
        "A learning project and a first-pass screening tool. Not investment "
        "advice, not a credit rating, and not a prediction of bankruptcy. "
        "Public data may be incomplete or restated; verify anything that "
        "matters against the company's own filings.")


# ---------------------------------------------------------------------------
# Market scan
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def market_scan_data():
    """The pre-screened benchmark set, loaded once per server process.

    Screening one company is something anyone can do by reading a filing.
    Screening thirty-six against one consistent ruler is the capability that
    separates an instrument from an opinion -- ask a person about thirty-six
    companies and you get thirty-six incomparable answers.

    Running the engine live over the whole set would take minutes and invite
    rate-limiting, so build_market_scan.py does it once and commits the result.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "market_scan.json")
    if not os.path.exists(path):
        return None, ("No market scan file found. Run "
                      "`python3 build_market_scan.py` to create one.")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, f"Could not read the market scan: {exc}"


def render_market_scan() -> None:
    """Every benchmarked company, ranked by stress, filterable by sector."""
    data, error = market_scan_data()
    if data is None:
        st.info(error)
        return

    companies = data["companies"]
    st.markdown("### Market scan")
    st.caption(
        f"{len(companies)} companies, same thresholds, ranked worst first. "
        f"Snapshot {data['generated']}.")

    counts = {}
    for row in companies:
        counts[row["rating"]] = counts.get(row["rating"], 0) + 1

    worst = companies[0] if companies else None
    elevated = counts.get(ELEVATED, 0)
    if worst:
        st.info(
            f"**{elevated} of {len(companies)} companies screen Elevated.** "
            f"Most stressed: **{worst['name']}** ({worst['ticker']}) at "
            f"{(worst['ratio'] or 0):.0%}.")

    cols = st.columns(4)
    with cols[0]:
        st.metric("Companies screened", len(companies))
    with cols[1]:
        st.metric("Elevated", counts.get(ELEVATED, 0))
    with cols[2]:
        st.metric("Moderate", counts.get(MODERATE, 0))
    with cols[3]:
        st.metric("Low", counts.get(LOW, 0))

    sectors = sorted({r["sector"] for r in companies if r["sector"]})
    left, right = st.columns([2, 1])
    with left:
        chosen = st.multiselect("Filter by sector", sectors, default=[],
                                placeholder="All sectors")
    with right:
        bands = st.multiselect("Filter by rating",
                               [ELEVATED, MODERATE, LOW], default=[],
                               placeholder="All ratings")

    rows = [r for r in companies
            if (not chosen or r["sector"] in chosen)
            and (not bands or r["rating"] in bands)]
    if not rows:
        st.info("No companies match those filters.")
        return

    # --- the ranked chart ------------------------------------------------
    frame = pd.DataFrame([{
        "Ticker": r["ticker"],
        "Company": r["name"],
        "Stress": (r["ratio"] or 0) * 100,
        "Rating": r["rating"].replace(" Stress", ""),
        "Sector": r["sector"] or "n/a",
        "Leverage": r["netDebtToEbitda"],
        "Coverage": r["interestCoverage"],
    } for r in rows])

    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("Ticker:N", sort=alt.EncodingSortField("Stress", order="descending"),
                    title=None),
            x=alt.X("Stress:Q", title="Stress score (% of assessable maximum)",
                    scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("Rating:N",
                            scale=alt.Scale(domain=["Low", "Moderate", "Elevated"],
                                            range=["#1a7f37", "#bf8700", "#b42318"]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=["Ticker", "Company", "Sector", "Rating",
                     alt.Tooltip("Stress:Q", format=".0f", title="Stress %"),
                     alt.Tooltip("Leverage:Q", format=".2f"),
                     alt.Tooltip("Coverage:Q", format=".2f")])
        .properties(height=max(260, 18 * len(frame)))
    )
    st.altair_chart(chart, use_container_width=True)

    # --- the table -------------------------------------------------------
    table = pd.DataFrame([{
        "#": r["rank"],
        "Ticker": r["ticker"],
        "Company": r["name"],
        "Sector": r["sector"] or "—",
        "Rating": r["rating"].replace(" Stress", ""),
        "Score": f"{(r['ratio'] or 0):.0%}",
        "Net debt/EBITDA": ("—" if r["netDebtToEbitda"] is None
                            else f"{r['netDebtToEbitda']:.2f}x"),
        "Coverage": ("—" if r["interestCoverage"] is None
                     else f"{r['interestCoverage']:.2f}x"),
        "Signals": f"{r['signalsFired']}/{r['signalsTotal']}",
        "Altman Z": "—" if r["zScore"] is None else f"{r['zScore']:.2f}",
    } for r in rows])
    st.dataframe(table, hide_index=True, use_container_width=True)

    # --- sector view -----------------------------------------------------
    medians = data.get("sectorMedians") or {}
    if medians and not chosen:
        st.markdown("#### Stress by sector")
        st.caption("Median stress by sector. Sectors with under three "
                   "companies are excluded.")
        sector_frame = pd.DataFrame(
            [{"Sector": k, "Median stress": v * 100}
             for k, v in sorted(medians.items(), key=lambda kv: -kv[1])])
        st.altair_chart(
            alt.Chart(sector_frame).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("Sector:N", sort="-x", title=None),
                x=alt.X("Median stress:Q", title="Median stress score (%)",
                        scale=alt.Scale(domain=[0, 100])),
                color=alt.value("#2a5d8f"),
                tooltip=["Sector",
                         alt.Tooltip("Median stress:Q", format=".0f")]
            ).properties(height=max(180, 30 * len(sector_frame))),
            use_container_width=True)

    st.caption(
        "Same engine as the single-company screen. Rebuild with "
        "`python3 build_market_scan.py`.")


def render_methodology() -> None:
    """How the rating works, and a sandbox for probing it.

    A rating nobody can interrogate is a black box regardless of how simple
    the rules are. This page lets a reader set each factor themselves and see
    the result move, which is a stronger claim to transparency than printing
    the thresholds and asking to be believed.
    """
    st.markdown("### How the rating works")
    st.caption("Five factors, fixed thresholds. Points divided by the "
               "maximum assessable, so gaps do not flatter.")

    # Short values: st.metric truncates anything wider than its column, and
    # "Moderate s..." is worse than no label at all.
    cols = st.columns(3)
    with cols[0]:
        st.metric("Below 30%", "Low")
    with cols[1]:
        st.metric("30 to 60%", "Moderate")
    with cols[2]:
        st.metric("Above 60%", "Elevated")

    st.markdown("#### Set each factor yourself")
    st.caption("Same scoring code the screener uses.")

    specs = [
        ("Leverage level", "lev", 3,
         ["Under 2.0x", "2.0 to 4.0x", "4.0 to 6.0x", "Above 6.0x"]),
        ("Leverage trend", "trend", 2,
         ["Improving or flat", "Worse by under 1.0x", "Worse by 1.0x or more"]),
        ("Interest coverage", "cov", 3,
         ["Above 6.0x", "3.0 to 6.0x", "1.5 to 3.0x", "Below 1.5x"]),
        ("Free cash flow", "fcf", 3,
         ["Positive both years", "Positive latest only",
          "Negative latest year", "Negative both years"]),
        ("EBITDA trend", "ebitda", 2,
         ["Growing or flat", "Down under 10%", "Down 10% or more"]),
    ]

    chosen: List[int] = []
    for label, key, max_points, options in specs:
        row = st.columns([3, 1])
        with row[0]:
            pick = st.select_slider(label, options=options,
                                    value=options[0], key=f"m_{key}")
        points = options.index(pick)
        chosen.append(points)
        with row[1]:
            st.metric("Points", f"{points} / {max_points}",
                      label_visibility="visible" if key == "lev" else "collapsed")

    total = sum(chosen)
    max_total = sum(spec[2] for spec in specs)
    ratio = total / max_total
    band = (LOW if ratio < LOW_CEILING
            else MODERATE if ratio < MODERATE_CEILING else ELEVATED)
    colour = RATING_COLORS[band]

    left, right = st.columns([1.15, 2], gap="large")
    with left:
        st.markdown(
            f"""<div class="rating-badge" style="background:{colour}">
                  <div class="label">Result</div>
                  <div class="value">{band.replace(' Stress', '')}</div>
                </div>""", unsafe_allow_html=True)
        st.caption(f"{total} of {max_total} points · {ratio:.0%}")
    with right:
        worst = max(range(len(specs)), key=lambda i: chosen[i] / specs[i][2])
        if total == 0:
            st.success("Every threshold is cleared — no factor scores a "
                       "single stress point.")
        elif total == max_total:
            st.error("Every factor is at its worst. This is the maximum the "
                     "rating can register.")
        else:
            st.info(f"Contributing most: **{specs[worst][0].lower()}**. "
                    "Note that no single factor can push a company past Low on "
                    "its own — distress is rarely one number, and the scoring "
                    "reflects that deliberately.")

    with st.expander("Why these five, and why no machine learning"):
        st.markdown(
            "**What each factor captures.** Leverage level is the *size* of "
            "the problem; leverage trend is the *direction*, which often "
            "matters more; interest coverage is the *urgency*, because missing "
            "a payment is an event of default; free cash flow says whether the "
            "situation is *self-correcting or worsening*; EBITDA trend is the "
            "*engine* driving all four.\n\n"
            "**Why rules rather than a fitted model.** Three reasons worth "
            "stating. Every point is explainable — if the output says "
            "Elevated, the factors and thresholds that produced it are on "
            "screen. The thresholds *are* the finance: 4x leverage and 3x "
            "coverage are real credit conventions, written down rather than "
            "buried in learned weights. And honest training data barely exists "
            "at this scale — corporate bankruptcies are rare, so a model "
            "fitted on a few hundred learns the quirks of that sample rather "
            "than a general rule.\n\n"
            "**What the rating is not.** It is a screening score, not a credit "
            "rating and not a prediction of default. Its only job is to decide "
            "whether a company deserves a closer look.")

    st.markdown("#### The pipeline")
    st.caption("Python calculates and decides. The explanation layer only "
               "describes. Same ticker, same output, every run.")
    st.markdown(
        '<div class="pipeline">Ticker → Financial data → Credit metrics → '
        'Signal detection → Stress test → Peer comparison → Rating → '
        'Explanation</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Industry watch
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_industry_news(days: int, limit: int):
    """Recent restructuring filings, cached for an hour.

    Five searches per refresh, so caching matters both for speed and for not
    hammering the SEC. Filings do not change once made, and new ones appear
    over hours rather than seconds, so an hour is generous.
    """
    return news.fetch_all(days=days, limit=limit)


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_briefing(window_days: int):
    """The computed industry briefing, cached for an hour.

    Ten SEC searches plus the press feeds, so this is the most expensive thing
    the app does. Filings do not change once made.
    """
    return briefing.build(window_days=window_days)


def render_briefing() -> None:
    """What the filings and headlines add up to, counted rather than written.

    The obvious way to summarise an industry is to hand headlines to a
    language model and ask for a paragraph: readable, unverifiable, different
    every run. This counts instead, and assembles the prose from the counts,
    so every sentence traces to a number shown beside it.
    """
    if not news.is_configured():
        st.info(
            "The briefing reads the SEC's filing search, which needs the same "
            "contact string as the EDGAR source. Set `SEC_USER_AGENT` to "
            "enable it.")
        return

    window = st.selectbox("Compare windows of", [30, 60, 90], index=1,
                          format_func=lambda d: f"{d} days",
                          key="brief_window")

    with st.spinner("Counting filings across two windows..."):
        try:
            data = fetch_briefing(window)
        except Exception as exc:
            st.error(f"Could not build the briefing: {exc}")
            return

    recent, prior = data.recent, data.prior
    change = data.change_pct

    cols = st.columns(4)
    with cols[0]:
        st.metric(f"Filings, last {recent.days}d", recent.total,
                  delta=(None if change is None
                         else f"{change:+.0%} vs prior {prior.days}d"),
                  delta_color="inverse")
    with cols[1]:
        st.metric("Bankruptcy items (1.03)", recent.by_item.get("1.03", 0),
                  help="8-K Item 1.03 is the SEC's prescribed item for "
                       "bankruptcy or receivership. A company cannot trigger "
                       "it by merely discussing bankruptcy.")
    with cols[2]:
        st.metric("Debt accelerations (2.04)", recent.by_item.get("2.04", 0),
                  help="Item 2.04 covers debt acceleration — typically what "
                       "follows a covenant breach.")
    with cols[3]:
        st.metric("Credit headlines", data.headline_count)

    st.markdown("#### The picture")
    for line in briefing.summarise(data):
        st.markdown(line)

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("#### By event type")
        if recent.by_category:
            frame = pd.DataFrame(
                [{"Event": k, "Filings": v}
                 for k, v in sorted(recent.by_category.items(),
                                    key=lambda kv: -kv[1])])
            st.altair_chart(
                alt.Chart(frame).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("Event:N", sort="-x", title=None),
                    x=alt.X("Filings:Q", title="Filings"),
                    color=alt.value("#b42318"),
                    tooltip=["Event", "Filings"]
                ).properties(height=max(160, 34 * len(frame))),
                use_container_width=True)

    with right:
        st.markdown("#### By industry")
        if recent.by_industry:
            top = recent.by_industry.most_common(8)
            frame = pd.DataFrame([{"Industry": k, "Filings": v}
                                  for k, v in top])
            st.altair_chart(
                alt.Chart(frame).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("Industry:N", sort="-x", title=None),
                    x=alt.X("Filings:Q", title="Filings"),
                    color=alt.value("#2a5d8f"),
                    tooltip=["Industry", "Filings"]
                ).properties(height=max(160, 30 * len(frame))),
                use_container_width=True)
            st.caption(
                "Grouped by SIC major group, the classification the filer "
                "registered under.")

    if data.themes:
        st.markdown("#### What the press is writing about")
        theme_frame = pd.DataFrame(
            [{"Term": t, "Headlines": n} for t, n in data.themes])
        st.altair_chart(
            alt.Chart(theme_frame).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("Term:N", sort="-y", title=None,
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Headlines:Q", title="Headlines"),
                color=alt.value("#2a5d8f"),
                tooltip=["Term", "Headlines"]
            ).properties(height=190),
            use_container_width=True)

    for err in data.errors:
        st.caption(err)
    st.caption(f"Built {data.generated}. Every figure is a count of real "
               "filings or headlines.")


@st.cache_data(show_spinner=False, ttl=1800)
def fetch_press_coverage(limit: int, filtered: bool):
    """Syndicated headlines, cached for half an hour.

    Seven feeds per refresh. Publishers update over minutes, and nobody needs
    a fresh pull per interaction.
    """
    return news.fetch_press(limit=limit, filtered=filtered)


def render_press() -> None:
    """What is being written, as opposed to what has been filed.

    The SEC feed reports formal disclosure. This reports journalism, which
    covers rumour, negotiation and sector pressure weeks before any of it
    reaches a filing -- and covers private credit, which barely files at all.
    """
    st.caption("Public RSS, filtered to credit and restructuring. Links open "
               "the publisher's site.")

    controls = st.columns([1, 1, 2])
    with controls[0]:
        count = st.selectbox("Show", [15, 30, 50], index=1, key="press_n")
    with controls[1]:
        only_credit = st.toggle("Credit only", value=True, key="press_f",
                                help="Off shows every headline from these "
                                     "feeds, including general business news.")

    try:
        articles = fetch_press_coverage(count, only_credit)
    except Exception as exc:
        st.error(f"Could not load headlines: {exc}")
        return

    if not articles:
        st.info(
            "No matching headlines right now. Try turning off the credit "
            "filter, or check back later — these feeds move through the day.")
        return

    with controls[2]:
        st.caption("")
        st.caption(f"{len(articles)} headlines from "
                   f"{len({a.source for a in articles})} publishers.")

    for article in articles:
        head = st.columns([5, 1])
        with head[0]:
            st.markdown(f"**[{article.title}]({article.link})**")
        with head[1]:
            st.caption(article.published or "")
        line = f"{article.source}"
        if article.matched:
            line += " · " + ", ".join(article.matched[:4])
        st.caption(line)
        if article.summary:
            st.caption(article.summary[:240])
        st.markdown("")

    st.caption(
        "Sources: " + ", ".join(news.feed_sources()) + ". Headlines and "
        "summaries come from each publisher's own public RSS feed. Refreshed "
        "every 30 minutes.")


def render_news() -> None:
    """Live restructuring activity, read from SEC filings rather than scraped.

    A news feed would mean scraping somebody's site: fragile, usually paid,
    and a journalist's summary of an event rather than the event. The SEC's
    full-text search is free, keyless, covers every US public filer, and
    returns the primary document — so every item here links to the filing a
    reader can check for themselves.
    """
    st.markdown("### Industry watch")
    st.caption(
        "**Briefing** — the numbers. **Filings** — individual SEC events. "
        "**Press** — what reporters are covering.")

    brief_tab, filings_tab, press_tab = st.tabs(
        ["Briefing", "SEC filings", "Press coverage"])
    with brief_tab:
        render_briefing()
    with filings_tab:
        render_filings()
    with press_tab:
        render_press()


def render_filings() -> None:
    """Restructuring events as formally filed with the SEC."""
    if not news.is_configured():
        st.info(
            "This section reads the SEC's full-text filing search, which "
            "requires the same contact string as the EDGAR data source. Set "
            "`SEC_USER_AGENT` to enable it — see the sidebar.")
        return

    st.caption("Restructuring events as companies file them. Every row "
               "links to the filing.")

    controls = st.columns([1, 1, 2])
    with controls[0]:
        window = st.selectbox("Look back", [30, 90, 180, 365], index=2,
                              format_func=lambda d: f"{d} days")
    with controls[1]:
        per = st.selectbox("Per category", [5, 10, 20], index=1)

    try:
        categories = fetch_industry_news(window, per)
    except Exception as exc:
        st.error(f"Could not load filings: {exc}")
        return

    total = sum(len(c.filings) for c in categories)
    if total == 0:
        st.info(
            "No filings came back. The SEC search may be unavailable, or the "
            "window may be too narrow — try a longer one.")
        return

    with controls[2]:
        st.caption("")
        st.caption(f"{total} filings across {len(categories)} event types, "
                   f"last {window} days.")

    for category in categories:
        st.markdown(f"#### {category.label}")
        st.caption(category.explanation)

        if not category.filings:
            st.caption("_Nothing filed in this window._")
            st.markdown("")
            continue

        rows = []
        for filing in category.filings:
            rows.append({
                "Filed": filing.date,
                "Company": filing.company,
                "Ticker": filing.primary_ticker or "—",
                "Form": filing.form,
                "Filing": filing.url,
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            column_config={
                "Filing": st.column_config.LinkColumn(
                    "Filing", display_text="Open on EDGAR"),
            })

        # The point of pairing a news feed with a screener: these companies
        # can be run through it. Tickers ending in Q are post-bankruptcy
        # symbols that the data sources usually no longer carry.
        screenable = sorted({f.primary_ticker for f in category.filings
                             if f.primary_ticker
                             and not f.primary_ticker.endswith("Q")})
        if screenable:
            st.caption("Screen any of these in the Company tab: "
                       + ", ".join(f"`{t}`" for t in screenable[:10]))
        st.markdown("")

    st.caption("Source: SEC EDGAR full-text search. Refreshed hourly.")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> Dict[str, object]:
    st.sidebar.markdown("### Settings")

    # Read before anything else draws, so the whole page renders in one theme.
    theme = st.sidebar.radio(
        "Appearance", list(THEMES.keys()), horizontal=True,
        key="theme_mode",
        help="Dark reads better on a projector in a darkened room; light "
             "reads better on paper-white screens and in daylight.")
    inject_theme(theme)

    # EDGAR is only offered when it can actually run. The SEC refuses
    # anonymous requests, so without SEC_USER_AGENT the option could only ever
    # produce an error -- and an interface that offers a choice which cannot
    # work is worse than one that offers fewer choices.
    from screener.edgar import EdgarError, user_agent
    try:
        user_agent()
        edgar_ready = True
    except EdgarError:
        edgar_ready = False

    options = ["Yahoo Finance (live)"]
    if edgar_ready:
        options.append("SEC EDGAR (official)")
    options.append("Local file (offline)")

    source_label = st.sidebar.radio(
        "Data source", options,
        help="Yahoo fetches any public ticker but is an unofficial scraper. "
             + ("SEC EDGAR is the actual regulatory filing — authoritative, "
                "though it covers only SEC filers. " if edgar_ready else "")
             + "Local files are synthetic teaching data that work with no "
               "internet.")
    source = {"Yahoo": "yfinance", "SEC E": "edgar"}.get(
        source_label[:5], "local")

    if source == "edgar":
        st.sidebar.caption(
            "Figures come from the company's own 10-K filings. Totals may "
            "differ from Yahoo's — notably total debt, where the two draw the "
            "boundary differently on leases.")

    years = st.sidebar.slider(
        "Years of history", min_value=2, max_value=5, value=5,
        help="Trends need at least two years. Three to five is enough to see "
             "a direction of travel.")

    # The Claude rewording layer is offered only when it can actually run --
    # the same rule applied to the EDGAR source. A disabled control that can
    # never be switched on is clutter, not a feature.
    #
    # Note what is NOT conditional: the explanations themselves. Those are
    # written by narrative.py in every configuration, so the app always
    # explains its findings. Claude would only reword them.
    st.sidebar.markdown("### Explanation")
    claude_ready = ai.is_configured()
    if claude_ready:
        use_claude = st.sidebar.toggle(
            "Use Claude for explanations", value=True,
            help="Off: prose assembled by Python from the computed figures — "
                 "deterministic and free. On: those same figures are sent to "
                 "Claude, which rewords them. Either way Python does every "
                 "calculation and decides the rating.")
    else:
        use_claude = False
        st.sidebar.caption(
            "Explanations are written by Python from the computed figures, so "
            "the wording is identical on every run. No language model is "
            "involved.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### The pipeline")
    st.sidebar.markdown(
        '<div class="pipeline">Ticker<br>→ Financial Data<br>'
        '→ Credit Metrics<br>→ Signal Detection<br>'
        '→ Stress Test<br>→ Summary</div>', unsafe_allow_html=True)
    st.sidebar.caption(
        "Python does every calculation, decides the rating and writes the "
        "explanation, so the output is identical on every run. An optional "
        "Claude layer can reword the prose; it never touches a number.")

    return {"source": source, "years": years,
            "use_claude": use_claude, "theme": theme}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_secrets_into_env() -> None:
    """Copy Streamlit secrets into the environment.

    Streamlit Community Cloud provides secrets through st.secrets, while the
    EDGAR and Claude layers read os.environ so they also work from the command
    line. This bridges the two, and stays silent when no secrets file exists,
    which is the normal case locally.
    """
    for key in ("SEC_USER_AGENT", "ANTHROPIC_API_KEY"):
        if os.environ.get(key):
            continue
        try:
            value = st.secrets[key]
        except Exception:
            continue
        if value:
            os.environ[key] = str(value)


def main() -> None:
    _load_secrets_into_env()
    # Paint the stored theme before any widget draws; render_sidebar() applies
    # it again after the radio is read, which covers a change made this run.
    inject_theme(st.session_state.get("theme_mode", "Light"))
    settings = render_sidebar()

    st.title("Credit Health & Restructuring Watch Agent")
    st.markdown(
        "Analyze a public company's leverage, debt-service ability, cash "
        "flow, and financial trends to identify potential signs of credit "
        "deterioration.")

    with st.form("ticker_form"):
        col1, col2 = st.columns([3, 1])
        with col1:
            ticker = st.text_input(
                "Enter company ticker", value="",
                placeholder="AAL",
                label_visibility="visible").strip().upper()
        with col2:
            st.write("")
            st.write("")
            submitted = st.form_submit_button("Analyze Company",
                                              type="primary",
                                              use_container_width=True)

    st.caption("This tool is for educational and analytical purposes and is "
               "not investment or lending advice.")

    if settings["source"] == "local":
        st.info("**Offline mode.** Two synthetic teaching companies are "
                "bundled: **EXMPL** (a deteriorating credit) and **HEALTHY** "
                "(a sound one). Both are invented figures, clearly labelled, "
                "and describe no real company. Switch the sidebar to Yahoo "
                "Finance for real tickers.")

    if submitted:
        if not ticker:
            st.error("Enter a ticker to analyze.")
        else:
            analysis = run_agent_workflow(
                ticker, settings["source"], settings["years"],
                settings["use_claude"])
            if analysis is not None:
                st.session_state["analysis"] = analysis
                st.session_state["analyzed_ticker"] = ticker
            else:
                # A failed run must clear any previous company, or the error
                # message would sit above a dashboard for a different ticker.
                st.session_state.pop("analysis", None)

    analysis = st.session_state.get("analysis")

    # Everything below the search box lives in tabs. Nine sections stacked on
    # one scrolling page made the tool look thinner than it is -- a reader
    # scrolling past a section perceives far less than one who chose to open
    # it. The tabs also separate two genuinely different tasks: screening one
    # company, and scanning the whole set.
    tab_labels = ["Company", "Market scan", "Industry watch", "Methodology",
                  "About"]
    (company_tab, scan_tab, news_tab, method_tab,
     about_tab) = st.tabs(tab_labels)

    with company_tab:
        if analysis is None:
            st.markdown(
                "#### Enter a ticker above to screen a company\n"
                "It answers one question: **is this company's credit profile "
                "improving or deteriorating, and are there warning signs that "
                "could eventually require restructuring analysis?**\n\n"
                "Seven reported figures per year become six credit metrics, "
                "seven warning signals, a downside stress test, a sector "
                "comparison and a transparent rating — with every number "
                "traceable to the filing it came from.")
            st.caption(
                "No internet? Switch the sidebar to **Local file (offline)** "
                "and try `EXMPL` or `HEALTHY`.")
        else:
            render_company(analysis)

    with scan_tab:
        render_market_scan()

    with news_tab:
        render_news()

    with method_tab:
        render_methodology()

    with about_tab:
        render_about()


def render_company(analysis: Dict[str, object]) -> None:
    """The single-company screen, as sub-tabs.

    Nine sections is too many to scroll. Grouped by the question each answers:
    where the company stands, how it got here, what could go wrong, and what
    to do next.
    """
    section_header(analysis["history"], analysis["metrics"])

    # The answer, in one line, before any chart. A reader should be able to
    # leave after this sentence and still know what the tool concluded.
    rating = analysis["rating"]
    metrics = analysis["metrics"]
    latest = metrics[-1]
    peers = analysis.get("peers") or {}

    bits = []
    if latest.net_debt_to_ebitda is not None:
        bits.append(f"{latest.net_debt_to_ebitda:.1f}x leverage")
    if latest.interest_coverage is not None:
        bits.append(f"{latest.interest_coverage:.1f}x coverage")
    if latest.free_cash_flow is not None:
        bits.append(("positive" if latest.free_cash_flow >= 0 else "negative")
                    + " free cash flow")
    headline = " · ".join(bits) if bits else "limited data"

    peer_note = ""
    if peers.get("available"):
        lev = next((m for m in peers["metrics"]
                    if m["key"] == "net_debt_to_ebitda"), None)
        if lev and lev["percentile"] is not None:
            peer_note = (f" That is the {lev['percentile']:.0f}th percentile "
                         f"of its sector.")

    band = {LOW: "success", MODERATE: "warning",
            ELEVATED: "error"}.get(rating.rating, "info")
    message = (f"**{rating.rating}** — {headline}.{peer_note}")
    getattr(st, band)(message)

    verdict, trends, risk, next_steps = st.tabs(
        ["Verdict", "Trends", "Risk", "What next"])

    with verdict:
        section_rating(analysis)
        st.markdown("---")
        section_metrics(analysis)
        st.markdown("---")
        section_peers(analysis)
        st.markdown("---")
        section_altman(analysis)

    with trends:
        section_explanation(analysis)
        st.markdown("---")
        section_trends(analysis)
        st.markdown("---")
        section_signals(analysis)

    with risk:
        section_scenario(analysis)
        st.markdown("---")
        section_maturities(analysis)

    with next_steps:
        section_restructuring_watch(analysis)
        st.markdown("---")
        section_limitations(analysis)


def render_about() -> None:
    """What the project is, how it is built, and what it cannot do."""
    st.markdown("### About this tool")
    st.markdown(
        "A first-pass credit screening instrument. It applies one consistent "
        "ruler to any public company and shows its work — it does not predict "
        "bankruptcy, and it is not investment or lending advice.")

    cols = st.columns(3)
    with cols[0]:
        st.metric("Data sources", "3")
        st.caption("Yahoo Finance, SEC EDGAR XBRL, offline files")
    with cols[1]:
        st.metric("Benchmark set", "211")
        st.caption("Companies across 11 sectors")
    with cols[2]:
        st.metric("Unit tests", "106")
        st.caption("Mostly covering missing and malformed data")

    st.markdown("#### What makes it an instrument rather than an opinion")
    st.markdown(
        "- **Reproducible.** The same ticker produces identical output every "
        "run — rating, score, wording and all. Python computes; the "
        "explanation layer only describes.\n"
        "- **It cannot invent a number.** Every figure comes from a tested "
        "function reading a reported line item.\n"
        "- **It refuses.** Negative EBITDA produces *not meaningful* rather "
        "than a flattering negative multiple. Untagged debt reports as "
        "unavailable rather than zero.\n"
        "- **One ruler.** All 211 benchmark companies meet the same "
        "thresholds, so the rankings compare.\n"
        "- **It shows its work.** Every rating point maps to a written "
        "threshold; every EDGAR figure names the XBRL tag it came from.")

    st.markdown("#### Two findings worth knowing")
    with st.expander("Ford screens at 39x leverage — correct arithmetic, wrong conclusion"):
        st.markdown(
            "Ford Credit funds a loan book, and that funding sits as debt on "
            "Ford's balance sheet. The loan book earns *interest income*, "
            "which is not part of EBITDA — so the numerator counts the "
            "finance debt while the denominator ignores the finance "
            "earnings.\n\n"
            "This is the characteristic failure mode of financial software: "
            "not a crash, but correct arithmetic producing a badly wrong "
            "conclusion. A blank cell announces itself; a confidently printed "
            "39.14x does not. Any reading above 15x is now flagged above the "
            "number, not in a footnote.")
    with st.expander("The same company can rate differently on different sources"):
        st.markdown(
            "American Airlines screens **Elevated** on Yahoo data and "
            "**Moderate** on SEC EDGAR. The arithmetic is identical; the "
            "inputs are defined differently. Yahoo counts operating leases in "
            "total debt and this EDGAR implementation does not — a gap of "
            "roughly 7,900m.\n\n"
            "Neither is wrong. The lesson is that **\"total debt\" is a "
            "definition, not a fact**, and a screen is only as consistent as "
            "what it feeds on. Professionals state their definitions for this "
            "reason, which is why every report here names its source.")

    st.markdown("#### What it cannot see")
    st.markdown(
        "- Covenant levels, which is often what actually triggers a "
        "restructuring\n"
        "- Undrawn credit facilities — the difference between a problem and a "
        "crisis\n"
        "- Whether a decline is cyclical or structural, the judgement that "
        "matters most\n"
        "- EBITDA quality: reported figures may carry generous add-backs\n"
        "- Anything inside a fiscal year — this is annual data")

    st.caption(
        "Educational and analytical use only. Not investment or lending "
        "advice, and not a prediction of default.")


if __name__ == "__main__":
    main()
