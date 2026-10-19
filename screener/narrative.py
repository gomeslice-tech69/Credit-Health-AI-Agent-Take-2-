"""
The explanation layer: turning computed facts into plain-language prose.

This module produces the "What is happening?" and "Why this matters" text. It
reads only values that metrics.py, signals.py, scenario.py and rating.py have
already computed. It performs NO arithmetic of its own beyond formatting.

TWO MODES, AND WHY THE DISTINCTION MATTERS

  1. TEMPLATE MODE (default, always available)
     Prose assembled from sentence fragments chosen by the computed facts.
     Deterministic: the same inputs always produce the same words. No API key,
     no network, no cost. This is what the app uses out of the box.

  2. CLAUDE MODE (optional, needs an API key)
     The same facts are handed to Claude, which rewords them more fluently.
     See ai.py. The facts are passed as data; Claude is instructed to use only
     the numbers given and never to introduce any of its own.

Be precise about this when presenting the project. Template mode is NOT "AI
explanation" and should not be described as such. It is Python choosing from
sentences a human wrote. That is honest, reproducible, and perfectly adequate.
Claude mode is the genuine language-model layer, and it is additive: it changes
the wording, never the numbers or the rating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .metrics import YearMetrics
from .models import FinancialHistory
from .rating import ELEVATED, INSUFFICIENT, LOW, MODERATE, StressRating
from .scenario import ScenarioResult
from .signals import Signal


@dataclass
class Narrative:
    """Every piece of prose the dashboard needs."""

    headline: str = ""              # one-line summary under the rating
    what_is_happening: str = ""     # the main paragraph
    why_it_matters: str = ""        # the consequence paragraph
    scenario_explanation: str = ""  # the downside-case paragraph
    rating_reasons: List[str] = field(default_factory=list)   # bullets
    analyst_questions: List[Tuple[str, str]] = field(default_factory=list)
    mode: str = "template"          # "template" or "claude"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_last(metrics: List[YearMetrics], attr: str
                ) -> Tuple[Optional[YearMetrics], Optional[YearMetrics]]:
    """Earliest and latest years for which `attr` could be computed."""
    usable = [m for m in metrics if getattr(m, attr) is not None]
    if len(usable) < 2:
        return (usable[0] if usable else None, None)
    return usable[0], usable[-1]


def _money(value: Optional[float], units: str, currency: str) -> str:
    """Format for prose, with the minus sign leading: '-USD 680m'."""
    if value is None:
        return "not available"
    suffix = "m" if units == "millions" else ""
    sign = "-" if value < 0 else ""
    return f"{sign}{currency} {abs(value):,.0f}{suffix}"


# ---------------------------------------------------------------------------
# The paragraphs
# ---------------------------------------------------------------------------

def _what_is_happening(history: FinancialHistory,
                       metrics: List[YearMetrics]) -> str:
    """The main descriptive paragraph: what the numbers did, in order."""
    name = history.short_name
    sentences: List[str] = []

    first_lev, last_lev = _first_last(metrics, "net_debt_to_ebitda")
    first_cov, last_cov = _first_last(metrics, "interest_coverage")
    years = history.sorted_years()

    # Opening sentence: the overall direction of travel.
    if first_lev and last_lev:
        delta = last_lev.net_debt_to_ebitda - first_lev.net_debt_to_ebitda
        if delta > 0.25:
            sentences.append(
                f"{name}'s financial position has weakened over the period "
                f"analysed. Net leverage increased from "
                f"{first_lev.net_debt_to_ebitda:.1f}x in {first_lev.year} to "
                f"{last_lev.net_debt_to_ebitda:.1f}x in {last_lev.year}.")
        elif delta < -0.25:
            sentences.append(
                f"{name}'s financial position has strengthened over the period "
                f"analysed. Net leverage fell from "
                f"{first_lev.net_debt_to_ebitda:.1f}x in {first_lev.year} to "
                f"{last_lev.net_debt_to_ebitda:.1f}x in {last_lev.year}.")
        else:
            sentences.append(
                f"{name}'s leverage has been broadly stable, moving from "
                f"{first_lev.net_debt_to_ebitda:.1f}x in {first_lev.year} to "
                f"{last_lev.net_debt_to_ebitda:.1f}x in {last_lev.year}.")
    else:
        sentences.append(
            f"Leverage could not be tracked across years for {name} because "
            "net debt or EBITDA was unavailable.")

    # Second sentence: WHY leverage moved.
    #
    # This is the single most important teaching point in the whole narrative.
    # Net Debt/EBITDA has two inputs, and the ratio moves if EITHER changes.
    # Saying "leverage rose" without saying which input drove it is close to
    # useless: debt rising to fund an acquisition and EBITDA collapsing produce
    # the same ratio but completely different situations.
    #
    # The four cases below are exhaustive, and the mixed case matters most.
    # When the two inputs pull in opposite directions, the naive reading picks
    # whichever one is checked first and gets the attribution backwards.
    if len(years) >= 2:
        first_y, last_y = years[0], years[-1]
        if (first_y.ebitda is not None and last_y.ebitda is not None
                and first_y.total_debt is not None
                and last_y.total_debt is not None
                and first_y.ebitda > 0 and first_y.total_debt > 0):
            ebitda_chg = (last_y.ebitda - first_y.ebitda) / first_y.ebitda
            debt_chg = (last_y.total_debt - first_y.total_debt) / first_y.total_debt

            # "Material" threshold: below 2% is noise, not a trend.
            ebitda_fell = ebitda_chg < -0.02
            ebitda_rose = ebitda_chg > 0.02
            debt_rose = debt_chg > 0.02
            debt_fell = debt_chg < -0.02

            if ebitda_fell and debt_rose:
                sentences.append(
                    f"Both inputs moved against the company: EBITDA fell "
                    f"{abs(ebitda_chg):.0%} while total debt rose "
                    f"{debt_chg:.0%}. Leverage rises fastest when earnings and "
                    "borrowings move in opposite directions like this.")
            elif ebitda_rose and debt_fell:
                sentences.append(
                    f"Both inputs moved in the company's favour: EBITDA rose "
                    f"{ebitda_chg:.0%} while total debt fell "
                    f"{abs(debt_chg):.0%}.")
            elif ebitda_fell and debt_fell:
                # Opposing forces. The leverage ratio itself settles which won.
                winner = ("debt reduction more than offset it"
                          if (last_lev and first_lev
                              and last_lev.net_debt_to_ebitda
                              < first_lev.net_debt_to_ebitda)
                          else "the earnings decline outweighed it")
                sentences.append(
                    f"The two inputs pulled in opposite directions: EBITDA "
                    f"fell {abs(ebitda_chg):.0%}, which pushes leverage up, "
                    f"while total debt fell {abs(debt_chg):.0%}, which pushes "
                    f"it down. On balance {winner}.")
            elif ebitda_rose and debt_rose:
                winner = ("earnings growth more than absorbed it"
                          if (last_lev and first_lev
                              and last_lev.net_debt_to_ebitda
                              < first_lev.net_debt_to_ebitda)
                          else "the extra borrowing outweighed it")
                sentences.append(
                    f"The two inputs pulled in opposite directions: total debt "
                    f"rose {debt_chg:.0%}, which pushes leverage up, while "
                    f"EBITDA rose {ebitda_chg:.0%}, which pushes it down. "
                    f"On balance {winner}.")
            elif ebitda_fell:
                sentences.append(
                    f"This was driven by earnings rather than borrowing: "
                    f"EBITDA fell {abs(ebitda_chg):.0%} while debt was broadly "
                    "unchanged. A company can become more leveraged without "
                    "borrowing a single dollar more, simply by earning less.")
            elif debt_rose:
                sentences.append(
                    f"This was driven by borrowing rather than earnings: debt "
                    f"rose {debt_chg:.0%} while EBITDA was broadly unchanged.")
            else:
                sentences.append(
                    "Neither EBITDA nor total debt changed materially over the "
                    "period.")

    # Third sentence: coverage, with its meaning spelled out.
    if first_cov and last_cov:
        if last_cov.interest_coverage < first_cov.interest_coverage - 0.1:
            sentences.append(
                f"At the same time, interest coverage declined from "
                f"{first_cov.interest_coverage:.1f}x to "
                f"{last_cov.interest_coverage:.1f}x, meaning the company's "
                "earnings provide a smaller cushion for servicing interest "
                "expense.")
        elif last_cov.interest_coverage > first_cov.interest_coverage + 0.1:
            sentences.append(
                f"Interest coverage improved from "
                f"{first_cov.interest_coverage:.1f}x to "
                f"{last_cov.interest_coverage:.1f}x, giving the company a "
                "larger cushion for servicing interest expense.")
        else:
            sentences.append(
                f"Interest coverage was broadly unchanged at "
                f"{last_cov.interest_coverage:.1f}x.")

    # Fourth sentence: cash flow, the test of whether this is self-correcting.
    fcf_years = [m for m in metrics if m.free_cash_flow is not None]
    if fcf_years:
        latest_fcf = fcf_years[-1]
        negative = [m for m in fcf_years if m.free_cash_flow < 0]
        cur, units = history.currency, history.units
        if latest_fcf.free_cash_flow < 0:
            sentences.append(
                f"Free cash flow was "
                f"{_money(latest_fcf.free_cash_flow, units, cur)} in "
                f"{latest_fcf.year}, so the business did not fund itself from "
                "operations and had to draw on cash, sell assets or borrow.")
            if len(negative) > 1:
                sentences.append(
                    f"This was not a one-off: free cash flow was negative in "
                    f"{len(negative)} of the {len(fcf_years)} years measured.")
        else:
            sentences.append(
                f"Free cash flow remained positive at "
                f"{_money(latest_fcf.free_cash_flow, units, cur)} in "
                f"{latest_fcf.year}, so the business funded itself from "
                "operations.")

    return " ".join(sentences)


def _why_it_matters(metrics: List[YearMetrics], rating: StressRating) -> str:
    """The consequence paragraph: so what?"""
    latest = metrics[-1] if metrics else None
    if latest is None:
        return "Not enough data to draw a conclusion."

    parts: List[str] = []
    coverage = latest.interest_coverage
    leverage = latest.net_debt_to_ebitda

    if rating.rating == ELEVATED:
        parts.append(
            "A company with rising leverage and declining interest coverage "
            "has less flexibility if earnings deteriorate further or borrowing "
            "costs rise.")
    elif rating.rating == MODERATE:
        parts.append(
            "The company is carrying real leverage but is not obviously "
            "stretched. The question is the direction of travel rather than "
            "the current position.")
    elif rating.rating == LOW:
        parts.append(
            "The company has financial flexibility: it can absorb a weaker "
            "year without its ability to service debt coming into question.")

    if coverage is not None:
        if coverage < 1.5:
            parts.append(
                f"At {coverage:.1f}x, interest coverage leaves very little "
                "margin for error. Interest is due on fixed dates and missing "
                "a payment is an event of default, which can allow lenders to "
                "demand immediate repayment of the whole loan.")
        elif coverage < 3.0:
            parts.append(
                f"At {coverage:.1f}x, interest coverage is adequate but tight. "
                "One materially worse year would bring it close to the level "
                "where lenders start to worry.")

    if leverage is not None and leverage > 6.0:
        parts.append(
            f"Net leverage above 6x (here {leverage:.1f}x) is where "
            "refinancing typically becomes difficult and expensive, which "
            "matters most when existing debt comes due.")

    parts.append(
        "None of this is a prediction. It identifies where an analyst should "
        "look first.")
    return " ".join(parts)


def scenario_explanation(result: ScenarioResult) -> str:
    """The downside-case paragraph, including the arithmetic lesson."""
    if not result.meaningful:
        return result.note

    pct = result.haircut
    if pct == 0:
        return ("No decline applied, so the stressed case is identical to the "
                "current position. Move the slider to apply a decline.")

    expected = 1.0 / (1.0 - pct) - 1.0
    parts = [
        f"A {pct:.0%} decline in EBITDA causes leverage to rise by about "
        f"{expected:.0%}, because the company's debt remains unchanged while "
        "earnings fall. Dividing by a smaller number moves the ratio further "
        "than the input moved, and interest coverage falls by the same "
        "proportion."
    ]

    after = result.stressed.interest_coverage
    before = result.base.interest_coverage
    if after is not None and before is not None:
        if after < 1.0:
            parts.append(
                f"Interest coverage would fall from {before:.1f}x to "
                f"{after:.1f}x. Below 1.0x, operating earnings no longer cover "
                "the interest bill at all, and the shortfall has to come from "
                "cash on hand or new borrowing.")
        elif after < 1.5:
            parts.append(
                f"Interest coverage would fall from {before:.1f}x to "
                f"{after:.1f}x, leaving almost no margin for error. Credit "
                "agreements often set minimum coverage covenants near this "
                "level.")
        elif after < 3.0:
            parts.append(
                f"Interest coverage would fall from {before:.1f}x to "
                f"{after:.1f}x. The company would still pay its interest, with "
                "limited room for a second bad year.")
        else:
            parts.append(
                f"Interest coverage would fall from {before:.1f}x to "
                f"{after:.1f}x and remain comfortable. The company absorbs "
                "this decline without its ability to service debt coming into "
                "question.")

    parts.append(
        "This is a sensitivity test, not a forecast: working capital, capex "
        "and borrowing are all held constant so that the single effect of "
        "lower earnings is visible on its own.")
    return " ".join(parts)


def _headline(rating: StressRating, metrics: List[YearMetrics]) -> str:
    """One line under the big rating badge."""
    if rating.rating == INSUFFICIENT:
        return "Not enough data to form a view."
    worsening = [f.name.lower().replace("ebitda", "EBITDA")
                 for f in rating.factors
                 if f.points is not None and f.points > 0]
    if not worsening:
        return ("Leverage, interest coverage, cash generation and earnings all "
                "screen comfortably.")
    if len(worsening) == 1:
        return f"The main concern is {worsening[0]}."
    assessed = rating.assessed_count
    return (f"Concerns across {len(worsening)} of the {assessed} factors "
            f"assessed, led by {worsening[0]} and {worsening[1]}.")



def _rating_reasons(rating: StressRating) -> List[str]:
    """Bullet list answering "Why this rating?" -- one line per factor that
    contributed points. This replaces a mysterious score with a reason."""
    reasons = []
    for f in rating.factors:
        if f.points is None:
            reasons.append(f"{f.name}: not assessed. {f.observation}")
        elif f.points > 0:
            reasons.append(f"{f.observation} ({f.points} of "
                           f"{f.max_points} stress points)")
    if not reasons:
        reasons.append("No factor scored any stress points.")
    return reasons


def analyst_questions(signals: List[Signal]) -> List[Tuple[str, str]]:
    """What an analyst should investigate next, as (question, why) pairs.

    Shared by the Streamlit app and the text report so the two never drift.
    The first two always appear because they are the most important things
    this tool structurally cannot see.
    """
    fired = {s.name for s in signals if s.status == "fired"}
    items: List[Tuple[str, str]] = [
        ("When does the company's debt mature?",
         "The most important question this tool cannot answer, because the "
         "screening data contains no maturity dates. 6x leverage with nothing "
         "due for five years is survivable; the same leverage with a large "
         "maturity next year is urgent. Found in the long-term debt note of "
         "the 10-K."),
        ("Can the company refinance its debt?",
         "If debt is coming due, can it be replaced, and at what cost? This "
         "depends on credit markets and on the company's own trajectory. "
         "Falling earnings plus a tight market is what turns a liquidity "
         "question into a restructuring."),
    ]

    if "Interest coverage decreasing" in fired:
        items.append((
            "What are the covenant levels, and how much headroom is left?",
            "Credit agreements usually require ratios to stay inside agreed "
            "limits. A breach can let lenders demand immediate repayment, "
            "which is frequently what starts a restructuring process."))
    if "Negative free cash flow" in fired:
        items.append((
            "Is negative free cash flow temporary or persistent?",
            "Add cash on hand to any undrawn revolving credit facility, then "
            "divide by the annual cash burn. That is the liquidity runway, and "
            "it determines how much time management has to fix the problem."))
    if "EBITDA falling" in fired or "Revenue falling" in fired:
        items.append((
            "Why has EBITDA declined -- is it cyclical or structural?",
            "The judgement that matters most, and that no ratio answers. A "
            "cyclical trough recovers and leverage normalises on its own; a "
            "structurally declining business does not, and its debt becomes "
            "permanently too large. Compare the trend with competitors: if the "
            "whole industry is down it is probably cyclical, if only this "
            "company is down it is losing share."))
    if "Cash decreasing" in fired:
        items.append((
            "Why is cash falling?",
            "Trace it through the cash flow statement. Cash spent on growth "
            "investment is a very different story from cash consumed by "
            "operating losses, and the headline decline looks identical."))

    items.append((
        "Has management discussed liquidity concerns?",
        "Read the Management's Discussion and Analysis section of the latest "
        "filing. Companies are required to disclose known liquidity risks, and "
        "the language used there often shifts before the numbers do."))
    items.append((
        "Is reported EBITDA clean?",
        "Check for add-backs -- costs management asks you to ignore as "
        "one-off. Some genuinely are; some recur every year. Adjusted EBITDA "
        "far above the unadjusted figure deserves scepticism, because every "
        "ratio here rests on that denominator."))
    return items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_narrative(history: FinancialHistory,
                    metrics: List[YearMetrics],
                    signals: List[Signal],
                    scenario_result: ScenarioResult,
                    rating: StressRating) -> Narrative:
    """Assemble all prose from already-computed facts. Deterministic."""
    return Narrative(
        headline=_headline(rating, metrics),
        what_is_happening=_what_is_happening(history, metrics),
        why_it_matters=_why_it_matters(metrics, rating),
        scenario_explanation=scenario_explanation(scenario_result),
        rating_reasons=_rating_reasons(rating),
        analyst_questions=analyst_questions(signals),
        mode="template",
    )


# ---------------------------------------------------------------------------
# Interpretation caveats
# ---------------------------------------------------------------------------

# Above this multiple, Debt/EBITDA has almost certainly stopped describing an
# operating business. No ordinary company can repay 15 years of EBITDA, so a
# reading this high nearly always means the debt is funding financial assets
# rather than operations.
IMPLAUSIBLE_LEVERAGE = 15.0


def structural_caveats(history: FinancialHistory,
                       metrics: List[YearMetrics]) -> List[Tuple[str, str]]:
    """Warnings that a metric, though correctly calculated, may not MEAN what
    it normally means for this particular company.

    This is a different thing from a missing value, and arguably more
    dangerous. A blank cell announces itself. A confidently-printed "39.14x"
    does not, and a reader will take it at face value.

    THE CASE THIS EXISTS FOR: companies with a captive finance arm. A car
    maker that lends customers the money to buy its cars carries enormous debt
    on its balance sheet, because that debt funds a loan book. The loan book
    earns interest income, which is not in EBITDA. So the numerator includes
    finance debt while the denominator excludes finance earnings, and the
    ratio becomes meaningless -- Ford screens around 39x, which would be
    catastrophic for a normal manufacturer and is simply the wrong lens here.

    The same applies in full to banks, insurers and leasing companies. A real
    analyst separates the industrial business from the finance business and
    computes leverage on the industrial side alone. That requires segment
    data this tool does not collect, so instead of guessing, it says plainly
    that the number should not be read in the usual way.

    Returned as (title, explanation) pairs so both front ends can show them.
    """
    caveats: List[Tuple[str, str]] = []
    latest = metrics[-1] if metrics else None
    if latest is None:
        return caveats

    leverage = latest.net_debt_to_ebitda
    if leverage is not None and leverage > IMPLAUSIBLE_LEVERAGE:
        caveats.append((
            f"Leverage of {leverage:.1f}x is implausibly high for an "
            "operating company — read it with care",
            "A multiple this large usually means the debt is not operating "
            "debt at all. The most common cause is a captive finance arm: a "
            "manufacturer that lends customers the money to buy its products "
            "carries that lending on its own balance sheet. That debt funds a "
            "loan book which earns interest income, and interest income is "
            "not part of EBITDA — so the numerator counts the finance debt "
            "while the denominator ignores the finance earnings. Banks, "
            "insurers and leasing companies produce the same effect for the "
            "same reason.\n\n"
            "What an analyst does instead: split the industrial business from "
            "the finance business and compute leverage on the industrial side "
            "alone, using the segment disclosures in the 10-K. This tool does "
            "not collect segment data, so it flags the reading rather than "
            "guessing at a split. Treat the stress rating for this company as "
            "unreliable until you have done that."))

    margin = latest.ebitda_margin
    if (margin is not None and 0 <= margin < 0.03
            and latest.net_debt_to_ebitda is not None
            and latest.net_debt_to_ebitda > 10):
        caveats.append((
            f"EBITDA margin of {margin:.1%} is very thin, which amplifies "
            "every ratio built on it",
            "When EBITDA is a small fraction of revenue, a modest change in "
            "costs moves it a long way in percentage terms — and every "
            "leverage and coverage figure here divides by it. The ratios are "
            "arithmetically correct but unstable: they will swing sharply "
            "year to year on small operating changes. Check whether the thin "
            "margin is normal for this industry before drawing conclusions "
            "from the trend."))

    return caveats


# ---------------------------------------------------------------------------
# Restructuring watch
# ---------------------------------------------------------------------------

def restructuring_watch(rating: StressRating,
                        signals: List[Signal],
                        metrics: List[YearMetrics]) -> Tuple[str, List[Tuple[str, str]]]:
    """Areas an analyst should look at next, given what the screen found.

    Returns (headline, [(area, why), ...]).

    WHAT THIS DELIBERATELY DOES NOT DO

    It does not design a restructuring, and it does not predict bankruptcy or
    default. Both would be beyond what seven figures a year can support, and
    predicting insolvency from a screening ratio is exactly the overreach that
    makes a tool like this untrustworthy.

    What it does instead is name the questions the metrics raise but cannot
    answer. That is the honest handoff from a screen to real analysis: the
    screen narrows a long list, and a person investigates what survived.

    Note how much of the list is about TIMING rather than size. Leverage tells
    you how big the debt is; it says nothing about when it comes due, and a
    company fails when it cannot make a payment on a date, not when a ratio
    crosses a threshold. That gap is the single biggest blind spot in this
    tool, which is why maturities lead the list whenever stress is elevated.
    """
    fired = {s.name for s in signals if s.status == "fired"}
    latest = metrics[-1] if metrics else None

    # --- The Low Stress case: say so plainly and stop. ---------------------
    if rating.rating == LOW:
        return (
            "No immediate restructuring warning signs are identified based on "
            "the metrics analyzed.",
            [("What would change this view",
              "Credit profiles deteriorate gradually. The things to re-check "
              "periodically are the same ones scored above: whether leverage "
              "starts rising, whether interest coverage starts falling, and "
              "whether free cash flow turns negative. A company moves from "
              "comfortable to stressed over several years, not in one "
              "quarter, so a screen like this is most useful run repeatedly "
              "rather than once.")],
        )

    if rating.rating == INSUFFICIENT:
        return (
            "Not enough data was available to form a view on restructuring "
            "risk.",
            [("Find the missing figures",
              "The screen could not compute enough of its factors to rate "
              "this company. Before drawing any conclusion, obtain the "
              "missing line items from the company's own 10-K or 10-Q "
              "filing. Absence of a warning here means absence of data, not "
              "absence of risk.")],
        )

    # --- Moderate or Elevated: name the specific questions. ----------------
    level = "elevated" if rating.rating == ELEVATED else "moderate"
    # Lower-case the factor names so they read naturally inside a sentence,
    # but put the acronym back -- "ebitda trend" looks like a typo.
    drivers = [f.name.lower().replace("ebitda", "EBITDA")
               for f in rating.factors
               if f.points is not None and f.points > 0]
    if drivers:
        driver_text = (drivers[0] if len(drivers) == 1
                       else " and ".join([", ".join(drivers[:-1]),
                                          drivers[-1]]))
        headline = (f"Credit stress is {level}, driven by {driver_text}. "
                    "An analyst may want to investigate the following before "
                    "drawing any conclusion.")
    else:
        headline = (f"Credit stress is {level}. An analyst may want to "
                    "investigate the following.")

    items: List[Tuple[str, str]] = [
        ("Upcoming debt maturities",
         "When does the debt actually come due? This is the most important "
         "question the screen cannot answer, because the data carries no "
         "maturity dates. High leverage with nothing due for several years is "
         "survivable; the same leverage with a large maturity next year is "
         "urgent. Found in the long-term debt note of the 10-K."),
        ("Ability to refinance existing debt",
         "If debt is coming due, can it be replaced, and at what cost? "
         "Refinancing depends on credit market conditions and on the "
         "company's own trajectory. Falling earnings combined with a tight "
         "market is what turns a liquidity question into a restructuring "
         "conversation."),
    ]

    if "Negative free cash flow" in fired or "Cash decreasing" in fired:
        items.append((
            "Liquidity and cash availability",
            "How long can the current position continue? Add cash on hand to "
            "any undrawn revolving credit facility, then divide by the annual "
            "cash burn. That ratio is the liquidity runway, and it determines "
            "how much time management has to fix the problem before they must "
            "negotiate with lenders."))

    if "EBITDA falling" in fired or "Revenue falling" in fired:
        items.append((
            "Whether EBITDA deterioration continues",
            "Is the decline cyclical or structural? A cyclical trough "
            "recovers and leverage normalises on its own; a structurally "
            "declining business does not, and its debt becomes permanently "
            "too large for it. Comparing the trend against competitors is the "
            "usual first test: if the whole industry is down it is probably "
            "cyclical, if only this company is down it is losing share."))

    if ("Interest coverage decreasing" in fired
            or (latest and latest.interest_coverage is not None
                and latest.interest_coverage < 3.0)):
        items.append((
            "Covenant headroom",
            "Credit agreements usually require ratios to stay within agreed "
            "limits, often a maximum leverage and a minimum interest "
            "coverage. Find the actual covenant levels in the credit "
            "agreement and calculate how much room is left. A breach can "
            "allow lenders to demand immediate repayment, and that is "
            "frequently what starts a restructuring process."))

    if rating.rating == ELEVATED:
        items.append((
            "Whether the company could support additional debt",
            "If more borrowing is needed to bridge a cash shortfall, would "
            "lenders provide it and on what terms? A company that can still "
            "raise money has options. One that cannot has far fewer, and that "
            "is usually the point at which existing creditors become part of "
            "the conversation."))

    items.append((
        "Management's own disclosure",
        "Read the Management's Discussion and Analysis section of the latest "
        "filing. Companies are required to disclose known liquidity risks and "
        "material uncertainties, and the language there often shifts before "
        "the reported numbers do."))

    return headline, items
