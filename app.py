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

import os
from typing import Dict, List, Optional

import altair as alt
import pandas as pd
import streamlit as st

from screener import ai
from screener.data_loader import DataLoadError, load_history
from screener.metrics import YearMetrics, compute_all_metrics
from screener.models import FinancialHistory
from screener.peers import (PeerCacheUnavailable, compare_to_sector,
                            load_peer_cache)
from screener.narrative import (build_narrative, restructuring_watch,
                                scenario_explanation,
                                structural_caveats)
from screener.rating import ELEVATED, INSUFFICIENT, LOW, MODERATE, rate_stress
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
    st.caption(
        "Every threshold in the rating is a general convention. The same "
        "leverage means different things in different industries, so these "
        "figures compare the company against the median of its sector.")

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
    st.caption("Three to five years is enough to see a direction of travel. "
               "The direction usually matters more than any single year's "
               "level.")

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
        st.altair_chart(
            trend_line_chart(frame, ["Net Debt / EBITDA", "Debt / EBITDA"],
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
    st.caption(f"{len(fired)} of {len(signals)} signals triggered. No single "
               "signal means a company is in trouble — each has an innocent "
               "explanation as well as a worrying one. What matters is how "
               "many fire together and whether they tell one coherent story.")

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
    st.caption("What happens if EBITDA falls? Debt, cash and interest expense "
               "are held constant, so the single effect of lower earnings is "
               "visible on its own.")

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

    source_label = st.sidebar.radio(
        "Data source",
        ["Yahoo Finance (live)", "Local file (offline)"],
        help="Yahoo Finance fetches any public ticker but is an unofficial "
             "source that occasionally omits line items. Local files are JSON "
             "you type from a 10-K; they work offline and are reliable for a "
             "demo.")
    source = "yfinance" if source_label.startswith("Yahoo") else "local"

    years = st.sidebar.slider(
        "Years of history", min_value=2, max_value=5, value=5,
        help="Trends need at least two years. Three to five is enough to see "
             "a direction of travel.")

    st.sidebar.markdown("### Explanation")
    claude_ready = ai.is_configured()
    use_claude = st.sidebar.toggle(
        "Use Claude for explanations", value=claude_ready,
        disabled=not claude_ready,
        help="Off: explanations are assembled by Python from sentence "
             "templates — deterministic and free. On: the computed figures are "
             "sent to Claude, which rewords them. Either way Python does all "
             "the arithmetic and decides the rating.")
    st.sidebar.caption(ai.status_message())

    st.sidebar.markdown("---")
    st.sidebar.markdown("### The pipeline")
    st.sidebar.markdown(
        '<div class="pipeline">Ticker<br>→ Financial Data<br>'
        '→ Credit Metrics<br>→ Signal Detection<br>'
        '→ Stress Test<br>→ Summary</div>', unsafe_allow_html=True)
    st.sidebar.caption(
        "Python does every calculation and decides the rating. The language "
        "model, when enabled, only describes the result — so the numbers are "
        "identical on every run.")

    return {"source": source, "years": years,
            "use_claude": use_claude, "theme": theme}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
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
    if analysis is None:
        st.markdown("---")
        st.markdown(
            "#### What this tool does\n"
            "It answers one question: **is this company's credit profile "
            "improving or deteriorating, and are there warning signs that "
            "could eventually require restructuring analysis?**\n\n"
            "It collects several years of seven figures — revenue, EBITDA, "
            "cash, total debt, interest expense, operating cash flow and "
            "capex — then computes six credit metrics, checks seven credit "
            "signals, runs a downside stress test, and scores the result "
            "against published thresholds you can read.\n\n"
            "It does **not** predict bankruptcy and does not design "
            "restructuring plans. It is a first-pass screen: a way to sort a "
            "long list of companies into *look harder* and *move on*.")
        return

    st.markdown("---")
    section_header(analysis["history"], analysis["metrics"])
    section_rating(analysis)
    st.markdown("---")
    section_metrics(analysis)
    st.markdown("---")
    section_peers(analysis)
    st.markdown("---")
    section_explanation(analysis)
    st.markdown("---")
    section_trends(analysis)
    st.markdown("---")
    section_signals(analysis)
    st.markdown("---")
    section_scenario(analysis)
    st.markdown("---")
    section_restructuring_watch(analysis)
    st.markdown("---")
    section_limitations(analysis)


if __name__ == "__main__":
    main()
