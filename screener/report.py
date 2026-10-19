"""
Stage 3: turning the computed results into the seven-section report.

This module does NO arithmetic. Every number it prints was already computed in
metrics.py, scenario.py or rating.py. Its only job is formatting and wording.

That separation is deliberate and worth defending: if formatting and
calculation are mixed together, you can never be sure whether a number in the
output came from the model or from a formatting shortcut. Here, every figure is
traceable to one pure function you can unit-test.
"""

from __future__ import annotations

from typing import List, Optional

from .metrics import YearMetrics
from .models import FinancialHistory
from .narrative import analyst_questions, structural_caveats
from .rating import (ELEVATED, LOW, LOW_CEILING, MODERATE,
                     MODERATE_CEILING, StressRating)
from .scenario import ScenarioResult
from .signals import Signal

WIDTH = 78
NA = "n/a"

# Band cut-offs, formatted once for the rating section.
LOW_CEILING_PCT = f"{LOW_CEILING:.0%}"
MODERATE_CEILING_PCT = f"{MODERATE_CEILING:.0%}"


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _x(value: Optional[float]) -> str:
    """Format a multiple, e.g. 3.14x."""
    return NA if value is None else f"{value:.2f}x"


def _money(value: Optional[float]) -> str:
    return NA if value is None else f"{value:,.0f}"


def _pct(value: Optional[float]) -> str:
    return NA if value is None else f"{value:+.1%}"


def _pct_plain(value: Optional[float]) -> str:
    return NA if value is None else f"{value:.1%}"


def _heading(text: str) -> List[str]:
    return ["", "=" * WIDTH, text.upper(), "=" * WIDTH]


def _sub(text: str) -> List[str]:
    return ["", text, "-" * len(text)]


def _wrap(text: str, indent: str = "") -> List[str]:
    """Wrap prose to the report width. Uses textwrap from the standard library."""
    import textwrap
    return textwrap.wrap(text, width=WIDTH, initial_indent=indent,
                         subsequent_indent=indent) or [""]


# ---------------------------------------------------------------------------
# The report sections
# ---------------------------------------------------------------------------

def _section_overview(history: FinancialHistory) -> List[str]:
    lines = _heading("1. Company overview")
    years = history.sorted_years()
    latest = history.latest()

    lines += [
        "",
        f"  Company      : {history.company_name}",
        f"  Ticker       : {history.ticker}",
        f"  Years covered: {years[0].year}-{years[-1].year} "
        f"({len(years)} fiscal years)",
        f"  Currency     : {history.currency} ({history.units})",
        f"  Data source  : {history.source}",
    ]
    lines += [""] + _wrap(f"Provenance: {history.provenance}", "  ")

    if history.notes:
        lines += ["", "  Data construction notes:"]
        for field_name, note in sorted(history.notes.items()):
            lines += _wrap(f"- {field_name}: {note}", "    ")

    if latest is not None:
        missing = latest.missing_fields()
        if missing:
            lines += [""] + _wrap(
                f"MISSING DATA in the latest year ({latest.year}): "
                f"{', '.join(missing)}. Metrics depending on these are shown "
                "as 'n/a' rather than estimated.", "  ")

    lines += ["", "  Latest reported figures:"]
    if latest is not None:
        for label, value in [
            ("Revenue", latest.revenue),
            ("EBITDA", latest.ebitda),
            ("Cash", latest.cash),
            ("Total debt", latest.total_debt),
            ("Interest expense", latest.interest_expense),
            ("Operating cash flow", latest.operating_cash_flow),
            ("Capital expenditure", latest.capex),
        ]:
            lines.append(f"    {label:<22}{_money(value):>14}")
    return lines


def _section_key_metrics(history: FinancialHistory,
                         metrics: List[YearMetrics]) -> List[str]:
    lines = _heading("2. Key metrics (latest fiscal year)")
    latest = metrics[-1]
    lines += ["", f"  Fiscal year {latest.year}:", ""]

    rows = [
        ("Debt / EBITDA", _x(latest.debt_to_ebitda), "debt_to_ebitda",
         "Years of EBITDA needed to repay all borrowings."),
        ("Net Debt / EBITDA", _x(latest.net_debt_to_ebitda), "net_debt_to_ebitda",
         "Same, after subtracting cash the company already holds."),
        ("Interest coverage", _x(latest.interest_coverage), "interest_coverage",
         "Times over the interest bill is covered by EBITDA."),
        ("Free cash flow", _money(latest.free_cash_flow), "free_cash_flow",
         "Operating cash flow minus capex: cash genuinely left over."),
        ("EBITDA margin", _pct_plain(latest.ebitda_margin), "ebitda_margin",
         "Operating earnings per dollar of sales."),
        ("Revenue growth", _pct(latest.revenue_growth), "revenue_growth",
         "Year-over-year change in the top line."),
    ]
    for label, value, key, explanation in rows:
        lines.append(f"  {label:<22}{value:>14}")
        lines += _wrap(explanation, "      ")
        if value == NA and key in latest.reasons:
            lines += _wrap(f"-> {latest.reasons[key]}", "      ")
        # A negative ratio is computable but needs saying out loud, because the
        # usual reading of the number ("covered N times over") breaks down.
        if key == "interest_coverage" and (latest.interest_coverage or 0) < 0:
            lines += _wrap(
                "-> Negative because EBITDA is negative: operating earnings "
                "cover none of the interest bill.", "      ")
        if key == "ebitda_margin" and (latest.ebitda_margin or 0) < 0:
            lines += _wrap(
                "-> Negative margin: the business lost money at the EBITDA "
                "level before any interest, tax or depreciation.", "      ")
        lines.append("")

    nd = latest.net_debt
    if nd is not None:
        lines += _wrap(f"Net debt (total debt less cash): {_money(nd)}", "  ")
    return lines


def _section_history(history: FinancialHistory,
                     metrics: List[YearMetrics]) -> List[str]:
    lines = _heading("3. Historical trends")
    lines += ["", "  How the credit profile has moved, oldest year first:", ""]

    header = (f"  {'Year':<6}{'Revenue':>10}{'EBITDA':>10}{'Margin':>9}"
              f"{'Debt/EB':>9}{'NetD/EB':>9}{'Cover':>8}{'FCF':>10}")
    lines += [header, "  " + "-" * (len(header) - 2)]

    years_by_number = {fy.year: fy for fy in history.sorted_years()}
    for m in metrics:
        fy = years_by_number[m.year]
        lines.append(
            f"  {m.year:<6}{_money(fy.revenue):>10}{_money(fy.ebitda):>10}"
            f"{_pct_plain(m.ebitda_margin):>9}{_x(m.debt_to_ebitda):>9}"
            f"{_x(m.net_debt_to_ebitda):>9}{_x(m.interest_coverage):>8}"
            f"{_money(m.free_cash_flow):>10}"
        )

    # Narrate each of the three dimensions an analyst reads first.
    lines += _sub("  What the table says")

    usable = [m for m in metrics if m.net_debt_to_ebitda is not None]
    if len(usable) >= 2:
        first, last = usable[0], usable[-1]
        delta = last.net_debt_to_ebitda - first.net_debt_to_ebitda
        direction = ("increased" if delta > 0.05 else
                     "decreased" if delta < -0.05 else "held roughly flat")
        lines += _wrap(
            f"LEVERAGE has {direction}, from "
            f"{first.net_debt_to_ebitda:.2f}x in {first.year} to "
            f"{last.net_debt_to_ebitda:.2f}x in {last.year} ({delta:+.2f}x). "
            "Remember this ratio can move for either of two reasons: more "
            "debt in the numerator, or less EBITDA in the denominator. "
            "Check the Revenue and EBITDA columns above to see which it was.",
            "  ")
    else:
        lines += _wrap("LEVERAGE: not enough data to describe a trend.", "  ")

    usable = [m for m in metrics if m.ebitda_margin is not None]
    if len(usable) >= 2:
        first, last = usable[0], usable[-1]
        delta = last.ebitda_margin - first.ebitda_margin
        direction = ("improved" if delta > 0.002 else
                     "deteriorated" if delta < -0.002 else "held roughly flat")
        lines += [""] + _wrap(
            f"PROFITABILITY has {direction}: EBITDA margin moved from "
            f"{first.ebitda_margin:.1%} in {first.year} to "
            f"{last.ebitda_margin:.1%} in {last.year} "
            f"({delta * 100:+.1f} percentage points).",
            "  ")

    usable = [m for m in metrics if m.free_cash_flow is not None]
    if usable:
        negative = [m.year for m in usable if m.free_cash_flow < 0]
        if not negative:
            story = (f"CASH FLOW has been positive in all {len(usable)} "
                     "assessable years: the business funded itself.")
        elif len(negative) == len(usable):
            story = (f"CASH FLOW was negative in all {len(usable)} assessable "
                     "years: the business consistently needed outside funding.")
        else:
            story = (f"CASH FLOW was negative in {len(negative)} of "
                     f"{len(usable)} assessable years "
                     f"({', '.join(str(y) for y in negative)}).")
        lines += [""] + _wrap(story, "  ")
    return lines


def _section_signals(signals: List[Signal]) -> List[str]:
    lines = _heading("4. Stress signals")
    fired = [s for s in signals if s.status == "fired"]
    clear = [s for s in signals if s.status == "clear"]
    unknown = [s for s in signals if s.status == "unknown"]

    lines += ["", f"  {len(fired)} of {len(signals)} signals triggered."]
    lines += [""] + _wrap(
        "IMPORTANT: no single signal means a company is in trouble. Each has "
        "an innocent explanation as well as a worrying one. What matters is "
        "how many fire together and whether they tell one coherent story.",
        "  ")

    if fired:
        lines += _sub("  Triggered")
        for s in fired:
            lines += [f"  [!] {s.name}"] + _wrap(s.detail, "      ")
            lines += _wrap(f"Why it matters: {s.why_it_matters}", "      ") + [""]
    if clear:
        lines += _sub("  Not triggered")
        for s in clear:
            lines += [f"  [ok] {s.name}"] + _wrap(s.detail, "       ")
    if unknown:
        lines += _sub("  Could not assess")
        for s in unknown:
            lines += [f"  [?] {s.name}"] + _wrap(s.detail, "      ")
    return lines


def _section_scenario(result: ScenarioResult) -> List[str]:
    lines = _heading(f"5. Downside scenario: {result.label}")

    if not result.meaningful:
        lines += [""] + _wrap(f"SCENARIO NOT APPLICABLE. {result.note}", "  ")
        return lines

    lines += [""] + _wrap(
        f"Holding debt, cash and interest expense constant, EBITDA is reduced "
        f"from {_money(result.base_ebitda)} to "
        f"{_money(result.stressed_ebitda)}. Only the three ratios that depend "
        "on EBITDA are recomputed.", "  ")

    lines += ["", f"  {'Metric':<22}{'Base':>10}{'Stressed':>12}{'Change':>12}", ""]
    for label, key in [("Debt / EBITDA", "debt_to_ebitda"),
                       ("Net Debt / EBITDA", "net_debt_to_ebitda"),
                       ("Interest coverage", "interest_coverage")]:
        before = getattr(result.base, key)
        after = getattr(result.stressed, key)
        delta = result.delta(key)
        lines.append(f"  {label:<22}{_x(before):>10}{_x(after):>12}"
                     f"{(_x(delta) if delta is None else f'{delta:+.2f}x'):>12}")

    lines += _sub("  What this means")
    expected = 1.0 / (1.0 - result.haircut) - 1.0
    lines += _wrap(
        f"Note that a {result.haircut:.0%} fall in EBITDA raises the leverage "
        f"ratios by about {expected:.0%}, not {result.haircut:.0%}. The debt "
        "did not change -- only the earnings used to measure it. Dividing by a "
        "smaller denominator moves the ratio more than the input moved. The "
        "same arithmetic cuts interest coverage by the same proportion.",
        "  ")
    lines += [""] + _wrap(
        "This asymmetry is the whole reason leverage creates fragility. An "
        "unlevered company that loses a fifth of its earnings has a bad year. "
        "A heavily levered company that loses a fifth of its earnings may "
        "breach a covenant or struggle to refinance.", "  ")

    after_cover = result.stressed.interest_coverage
    if after_cover is not None:
        if after_cover < 1.0:
            verdict = ("Under this scenario EBITDA would no longer cover the "
                       "interest bill at all. That is the point at which a "
                       "company must find cash elsewhere simply to stay "
                       "current on its debt.")
        elif after_cover < 1.5:
            verdict = ("Under this scenario interest coverage falls below "
                       "1.5x, leaving very little margin for error. Covenants "
                       "are often set near this level.")
        elif after_cover < 3.0:
            verdict = ("Under this scenario interest coverage remains above "
                       "1.5x but is tight. The company would still pay its "
                       "interest, with limited room for a second bad year.")
        else:
            verdict = ("Under this scenario interest coverage remains "
                       "comfortable. The company absorbs this decline without "
                       "its ability to service debt coming into question.")
        lines += [""] + _wrap(verdict, "  ")

    lines += [""] + _wrap(
        "Limitation: this is a sensitivity test, not a forecast. In a real "
        "downturn working capital, capex and borrowing would all move too. "
        "Holding them constant isolates the single effect of lower earnings.",
        "  ")
    return lines


def _section_rating(rating: StressRating,
                    history: FinancialHistory,
                    metrics: List[YearMetrics]) -> List[str]:
    lines = _heading("6. Overall financial stress")
    lines += ["", f"  RATING: {rating.rating.upper()}"]
    if rating.ratio is not None:
        lines.append(f"  Score : {rating.score} of {rating.max_score} possible "
                     f"stress points ({rating.ratio:.0%})")
    lines += [""] + _wrap(rating.confidence_note, "  ")

    lines += _sub("  How the score was built")
    for f in rating.factors:
        points = "not assessed" if f.points is None else \
                 f"{f.points} / {f.max_points} pts"
        lines += ["", f"  {f.name} -- {points}"]
        lines += _wrap(f.observation, "      ")
        lines += _wrap(f"Scale: {f.threshold_note}", "      ")

    caveats = structural_caveats(history, metrics)
    if caveats:
        lines += _sub("  !! INTERPRETATION WARNINGS")
        for title, explanation in caveats:
            lines += _wrap(f"* {title}", "  ")
            for paragraph in explanation.split("\n\n"):
                lines += [""] + _wrap(paragraph, "    ")
            lines.append("")

    lines += _sub("  Reading the bands")
    lines += _wrap(
        f"Points are summed and divided by the maximum that could actually be "
        f"assessed. Below {LOW_CEILING_PCT} = {LOW}; "
        f"{LOW_CEILING_PCT} to {MODERATE_CEILING_PCT} = {MODERATE}; "
        f"above {MODERATE_CEILING_PCT} = {ELEVATED}.", "  ")
    lines += [""] + _wrap(
        "This is a screening score, not a credit rating and not a prediction "
        "of default. Its only purpose is to decide whether a company deserves "
        "a closer look. Every point above can be traced to one stated "
        "threshold, which is the point of building it this way.", "  ")
    return lines


def _section_next_steps(signals: List[Signal],
                        rating: StressRating,
                        history: FinancialHistory) -> List[str]:
    """What an analyst should investigate next.

    The questions come from narrative.analyst_questions() so that this text
    report and the Streamlit dashboard can never drift apart.
    """
    lines = _heading("7. What an analyst might investigate next")
    lines += ["", f"  Based on the signals that fired for {history.ticker}:"]

    for i, (question, why) in enumerate(analyst_questions(signals), 1):
        lines += [""] + _wrap(f"{i}. {question}", "  ")
        lines += _wrap(why, "     ")

    if rating.rating == ELEVATED:
        lines += ["", "  " + "-" * (WIDTH - 2)] + _wrap(
            "This company screened as Elevated Stress, which means it warrants "
            "a closer look -- not that it is heading for bankruptcy. The "
            "purpose of a screen is to sort a large list into 'look harder' "
            "and 'move on'. The analysis above is where the real work starts, "
            "not where it concludes.", "  ")
    return lines


def build_report(history: FinancialHistory,
                 metrics: List[YearMetrics],
                 signals: List[Signal],
                 scenario_result: ScenarioResult,
                 rating: StressRating) -> str:
    """Assemble the full seven-section report as one string."""
    lines: List[str] = [
        "#" * WIDTH,
        f"FINANCIAL DISTRESS SCREENING REPORT - {history.ticker}",
        f"{history.company_name}",
        "#" * WIDTH,
        "",
    ]
    lines += _wrap(
        "A first-pass screening tool. It flags warning signs for an analyst to "
        "investigate. It does not predict bankruptcy, is not investment "
        "advice, and is not a credit rating.", "  ")

    lines += _section_overview(history)
    lines += _section_key_metrics(history, metrics)
    lines += _section_history(history, metrics)
    lines += _section_signals(signals)
    lines += _section_scenario(scenario_result)
    lines += _section_rating(rating, history, metrics)
    lines += _section_next_steps(signals, rating, history)

    lines += ["", "=" * WIDTH, "END OF REPORT", "=" * WIDTH, ""]
    return "\n".join(lines)
