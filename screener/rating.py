"""
Stage 2d: the stress rating.

Five factors. Each scores points against published thresholds. Add them up,
divide by the maximum that was actually assessable, and read off a band.

WHY IT IS BUILT THIS WAY

You could predict financial distress with a machine-learning model, and people
do. This project deliberately does not, for three reasons worth being able to
state:

  1. You can explain every point. If the output says "Elevated", you can say
     precisely which factors contributed and what threshold each one crossed.
     A gradient-boosted model cannot be defended in a meeting that way.
  2. The thresholds are the finance. The numbers below ARE the credit
     conventions -- 4x leverage, 3x coverage. Writing them down explicitly
     means the finance is visible in the code, not buried in fitted weights.
  3. Honest training data for corporate distress barely exists at this scale.
     Bankruptcies are rare, so a model fitted on a few hundred of them learns
     the quirks of that sample. A transparent rule set does not pretend to a
     precision it does not have.

The five factors, and why each one earns its place:

  1. LEVERAGE LEVEL     - the size of the problem
  2. LEVERAGE TREND     - the direction, which matters more than the level
  3. INTEREST COVERAGE  - the urgency; this is what forces a default
  4. FREE CASH FLOW     - whether the situation is self-correcting or worsening
  5. EBITDA TREND       - the engine driving all four of the above

Together they ask: how bad, getting better or worse, how urgent, self-funding,
and why.

A NOTE ON MISSING DATA. A factor we cannot assess scores no points AND removes
its points from the maximum, so the score stays a fair fraction of what was
actually measurable. Treating unknowns as zero would quietly bias every
under-reported company towards "Low Stress" -- exactly backwards, since poor
disclosure is itself a reason for caution. The report states how many factors
were assessed, and the rating is marked low-confidence below four.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .metrics import YearMetrics

LOW = "Low Stress"
MODERATE = "Moderate Stress"
ELEVATED = "Elevated Stress"
INSUFFICIENT = "Insufficient Data"


@dataclass
class Factor:
    """One scored factor, with its reasoning attached."""

    name: str
    points: Optional[int]        # None = could not assess
    max_points: int
    observation: str             # what the data showed
    threshold_note: str          # the scale this was scored against

    @property
    def assessed(self) -> bool:
        return self.points is not None


@dataclass
class StressRating:
    rating: str
    score: int
    max_score: int
    ratio: Optional[float]
    factors: List[Factor] = field(default_factory=list)
    confidence_note: str = ""

    @property
    def assessed_count(self) -> int:
        return sum(1 for f in self.factors if f.assessed)


# ---------------------------------------------------------------------------
# The thresholds. All of them, in one place, so they are easy to find,
# easy to defend, and easy to change.
# ---------------------------------------------------------------------------

# Factor 1: Net Debt / EBITDA level. 0 = conservative, 3 = stressed.
LEVERAGE_BANDS = [
    (2.0, 0, "below 2.0x"),
    (4.0, 1, "2.0x to 4.0x"),
    (6.0, 2, "4.0x to 6.0x"),
    (float("inf"), 3, "above 6.0x"),
]

# Factor 3: Interest coverage. Reversed -- HIGHER coverage is better.
COVERAGE_BANDS = [
    (1.5, 3, "below 1.5x"),
    (3.0, 2, "1.5x to 3.0x"),
    (6.0, 1, "3.0x to 6.0x"),
    (float("inf"), 0, "above 6.0x"),
]



# ---------------------------------------------------------------------------
# Pure scoring
#
# Each function below turns one raw value into points. They hold the only copy
# of the threshold logic: the Factor builders further down call them, and so
# does the what-if panel in the app. A second copy of "4.0x scores 2 points"
# would eventually disagree with this one.
# ---------------------------------------------------------------------------

def score_leverage_level(value: Optional[float]) -> Tuple[int, str]:
    """Net Debt/EBITDA -> points. Negative means a net cash position."""
    if value is None:
        return 0, "not available"
    if value < 0:
        return 0, "net cash position"
    for ceiling, points, label in LEVERAGE_BANDS:
        if value < ceiling:
            return points, label
    return 3, "above 6.0x"


def score_leverage_trend(delta: Optional[float]) -> Tuple[int, str]:
    """Change in Net Debt/EBITDA, earliest to latest -> points."""
    if delta is None:
        return 0, "not available"
    if delta <= 0:
        return 0, "improving or flat"
    return (1, "worse by under 1.0x") if delta < 1.0 else (2, "worse by 1.0x or more")


def score_coverage_value(value: Optional[float]) -> Tuple[int, str]:
    """Interest coverage -> points. Reversed: higher is better."""
    if value is None:
        return 0, "not available"
    if value < 0:
        return 3, "negative — EBITDA does not cover interest"
    for ceiling, points, label in COVERAGE_BANDS:
        if value < ceiling:
            return points, label
    return 0, "above 6.0x"


# Free cash flow is a state rather than a number: what happened in the last
# two years. The index is the score, which is why the order matters.
FCF_STATES = [
    "positive in both years",
    "positive in the latest year only",
    "negative in the latest year",
    "negative in both years",
]


def score_fcf_state(state_index: int) -> Tuple[int, str]:
    state_index = max(0, min(len(FCF_STATES) - 1, int(state_index)))
    return state_index, FCF_STATES[state_index]


def score_ebitda_change(change: Optional[float]) -> Tuple[int, str]:
    """Fractional change in EBITDA, earliest to latest -> points."""
    if change is None:
        return 0, "not available"
    if change >= 0:
        return 0, "growing or flat"
    return (1, "down under 10%") if change > -0.10 else (2, "down 10% or more")


def rate_from_inputs(leverage: Optional[float],
                     leverage_change: Optional[float],
                     coverage: Optional[float],
                     fcf_state: int,
                     ebitda_change: Optional[float]) -> StressRating:
    """Score the five factors directly from raw values.

    Used by the what-if panel, where the reader moves each input by hand.
    Shares every threshold with the normal path, so a hand-set 8.7x scores
    exactly what a measured 8.7x would.
    """
    specs = [
        ("Leverage level", 3, score_leverage_level(leverage)),
        ("Leverage trend", 2, score_leverage_trend(leverage_change)),
        ("Interest coverage", 3, score_coverage_value(coverage)),
        ("Free cash flow", 3, score_fcf_state(fcf_state)),
        ("EBITDA trend", 2, score_ebitda_change(ebitda_change)),
    ]
    factors = [
        Factor(name=name, points=points, max_points=cap,
               observation=label, threshold_note="")
        for name, cap, (points, label) in specs
    ]
    score = sum(f.points or 0 for f in factors)
    max_score = sum(f.max_points for f in factors)
    ratio = score / max_score if max_score else None

    if ratio is None:
        band = INSUFFICIENT
    elif ratio < LOW_CEILING:
        band = LOW
    elif ratio < MODERATE_CEILING:
        band = MODERATE
    else:
        band = ELEVATED

    return StressRating(band, score, max_score, ratio, factors,
                        "Scored from values set by hand.")


def _score_leverage_level(latest: YearMetrics) -> Factor:
    """How leveraged is the company right now?"""
    note = ("Net Debt/EBITDA: <2.0x = 0 pts, 2.0-4.0x = 1, "
            "4.0-6.0x = 2, >6.0x = 3")
    value = latest.net_debt_to_ebitda

    if value is None:
        reason = latest.reasons.get("net_debt_to_ebitda", "not available")
        # A negative-EBITDA company is the most stressed case there is, so it
        # must not slip through as "unassessed". It takes full points.
        if "negative" in reason:
            return Factor("Leverage level", 3, 3,
                          "EBITDA is negative, so leverage cannot be expressed "
                          "as a multiple. Treated as maximum stress: no "
                          "multiple of negative earnings can repay debt.",
                          note)
        return Factor("Leverage level", None, 3,
                      f"Could not assess ({reason}).", note)

    # Net debt below zero means more cash than debt -- a net cash position.
    if value < 0:
        return Factor("Leverage level", 0, 3,
                      f"Net Debt/EBITDA is {value:.2f}x: the company holds "
                      "more cash than debt (a net cash position).", note)

    for ceiling, points, label in LEVERAGE_BANDS:
        if value < ceiling:
            return Factor("Leverage level", points, 3,
                          f"Net Debt/EBITDA is {value:.2f}x ({label}).", note)
    return Factor("Leverage level", 3, 3, f"Net Debt/EBITDA is {value:.2f}x.", note)


def _score_leverage_trend(all_metrics: List[YearMetrics]) -> Factor:
    """Is leverage rising or falling? Direction over level."""
    note = ("Change in Net Debt/EBITDA, earliest to latest year: "
            "improving or flat = 0 pts, worse by <1.0x = 1, worse by >=1.0x = 2")

    usable = [m for m in all_metrics if m.net_debt_to_ebitda is not None]
    if len(usable) < 2:
        return Factor("Leverage trend", None, 2,
                      "Could not assess (need Net Debt/EBITDA for at least "
                      "two years).", note)

    first, last = usable[0], usable[-1]
    delta = last.net_debt_to_ebitda - first.net_debt_to_ebitda
    span = f"{first.year} to {last.year}"

    if delta <= 0:
        return Factor("Leverage trend", 0, 2,
                      f"Leverage improved or held flat over {span}: "
                      f"{first.net_debt_to_ebitda:.2f}x to "
                      f"{last.net_debt_to_ebitda:.2f}x ({delta:+.2f}x).", note)
    points = 1 if delta < 1.0 else 2
    return Factor("Leverage trend", points, 2,
                  f"Leverage rose over {span}: "
                  f"{first.net_debt_to_ebitda:.2f}x to "
                  f"{last.net_debt_to_ebitda:.2f}x ({delta:+.2f}x).", note)


def _score_coverage(latest: YearMetrics) -> Factor:
    """Can the company afford its interest bill?"""
    note = ("Interest coverage (EBITDA/interest): >6.0x = 0 pts, "
            "3.0-6.0x = 1, 1.5-3.0x = 2, <1.5x = 3")
    value = latest.interest_coverage

    if value is None:
        reason = latest.reasons.get("interest_coverage", "not available")
        if "negative" in reason:
            return Factor("Interest coverage", 3, 3,
                          "EBITDA is negative, so operating earnings do not "
                          "cover any of the interest bill. Maximum stress.",
                          note)
        return Factor("Interest coverage", None, 3,
                      f"Could not assess ({reason}).", note)

    # Negative coverage means EBITDA itself is negative. It scores maximum
    # points like any sub-1.5x reading, but the wording has to be different:
    # "-2.18x" does not sensibly read as "covered -2.18 times over".
    if value < 0:
        return Factor("Interest coverage", 3, 3,
                      f"Interest coverage is {value:.2f}x, which is negative "
                      "because EBITDA is negative. Operating earnings cover "
                      "none of the interest bill: the interest has to be paid "
                      "out of cash reserves or new borrowing.", note)

    for ceiling, points, label in COVERAGE_BANDS:
        if value < ceiling:
            return Factor("Interest coverage", points, 3,
                          f"Interest coverage is {value:.2f}x ({label}).", note)
    return Factor("Interest coverage", 0, 3,
                  f"Interest coverage is {value:.2f}x.", note)


def _score_free_cash_flow(all_metrics: List[YearMetrics]) -> Factor:
    """Is the company funding itself, or does it need outside money?"""
    note = ("Free cash flow: positive in both of the last two years = 0 pts, "
            "positive latest only = 1, negative latest only = 2, "
            "negative in both = 3")

    usable = [m for m in all_metrics if m.free_cash_flow is not None]
    if not usable:
        return Factor("Free cash flow", None, 3,
                      "Could not assess (operating cash flow or capex "
                      "unavailable).", note)

    latest = usable[-1]
    prior = usable[-2] if len(usable) >= 2 else None
    latest_negative = latest.free_cash_flow < 0

    if prior is None:
        points = 2 if latest_negative else 0
        return Factor("Free cash flow", points, 3,
                      f"FCF in {latest.year} was {latest.free_cash_flow:,.0f} "
                      f"({'negative' if latest_negative else 'positive'}). "
                      "Only one year assessable.", note)

    prior_negative = prior.free_cash_flow < 0
    if latest_negative and prior_negative:
        points, desc = 3, "negative in both years - a sustained cash shortfall"
    elif latest_negative:
        points, desc = 2, "turned negative in the latest year"
    elif prior_negative:
        points, desc = 1, "recovered to positive after a negative prior year"
    else:
        points, desc = 0, "positive in both years"

    return Factor("Free cash flow", points, 3,
                  f"FCF was {prior.free_cash_flow:,.0f} in {prior.year} and "
                  f"{latest.free_cash_flow:,.0f} in {latest.year}: {desc}.", note)


def _score_ebitda_trend(all_metrics: List[YearMetrics],
                        ebitda_by_year: List[tuple]) -> Factor:
    """Are operating earnings growing or shrinking?"""
    note = ("EBITDA change, earliest to latest year: growing or flat = 0 pts, "
            "down less than 10% = 1, down 10% or more = 2")

    usable = [(y, e) for y, e in ebitda_by_year if e is not None]
    if len(usable) < 2:
        return Factor("EBITDA trend", None, 2,
                      "Could not assess (need EBITDA for at least two years).",
                      note)

    (first_year, first_e), (last_year, last_e) = usable[0], usable[-1]
    if first_e <= 0:
        return Factor("EBITDA trend", 2, 2,
                      f"EBITDA was {first_e:,.0f} in {first_year}: not positive, "
                      "so a percentage change is not meaningful. Scored as a "
                      "deterioration.", note)

    chg = (last_e - first_e) / abs(first_e)
    span = f"{first_year} to {last_year}"
    if chg >= 0:
        points, desc = 0, "growing"
    elif chg > -0.10:
        points, desc = 1, "modestly declining"
    else:
        points, desc = 2, "declining materially"
    return Factor("EBITDA trend", points, 2,
                  f"EBITDA moved {chg:+.1%} over {span} "
                  f"({first_e:,.0f} to {last_e:,.0f}): {desc}.", note)


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------

# Band cut-offs on score / max_assessable_score.
LOW_CEILING = 0.30       # below 30% of possible stress points -> Low
MODERATE_CEILING = 0.60  # 30-60% -> Moderate; above -> Elevated
MIN_FACTORS_FOR_CONFIDENCE = 4


def rate_stress(all_metrics: List[YearMetrics],
                ebitda_by_year: List[tuple]) -> StressRating:
    """Score the five factors and return a rating.

    `ebitda_by_year` is a list of (year, ebitda) tuples, needed because the
    EBITDA trend factor works off raw EBITDA rather than a computed ratio.
    """
    if not all_metrics:
        return StressRating(INSUFFICIENT, 0, 0, None, [],
                            "No metrics could be computed.")

    latest = all_metrics[-1]
    factors = [
        _score_leverage_level(latest),
        _score_leverage_trend(all_metrics),
        _score_coverage(latest),
        _score_free_cash_flow(all_metrics),
        _score_ebitda_trend(all_metrics, ebitda_by_year),
    ]

    score = sum(f.points for f in factors if f.points is not None)
    max_score = sum(f.max_points for f in factors if f.assessed)
    assessed = sum(1 for f in factors if f.assessed)

    if max_score == 0:
        return StressRating(INSUFFICIENT, 0, 0, None, factors,
                            "None of the five factors could be assessed with "
                            "the available data.")

    ratio = score / max_score
    if ratio < LOW_CEILING:
        rating = LOW
    elif ratio < MODERATE_CEILING:
        rating = MODERATE
    else:
        rating = ELEVATED

    if assessed < MIN_FACTORS_FOR_CONFIDENCE:
        note = (f"LOW CONFIDENCE: only {assessed} of 5 factors could be "
                "assessed. Treat this rating as provisional and check the "
                "missing data before relying on it.")
    else:
        note = f"All {assessed} of 5 factors assessed." if assessed == 5 else \
               f"{assessed} of 5 factors assessed."

    return StressRating(rating, score, max_score, ratio, factors, note)


# ---------------------------------------------------------------------------
# Rating trajectory
# ---------------------------------------------------------------------------

@dataclass
class RatingPoint:
    """The rating as it would have stood at the end of one fiscal year."""

    year: int
    rating: str
    score: int
    max_score: int
    ratio: Optional[float]
    assessed: int


def rating_trajectory(history, compute_metrics) -> List[RatingPoint]:
    """Recompute the rating as of each year, using only data available then.

    WHY THIS IS WORTH HAVING

    A single rating tells you where a company stands. It does not tell you
    when it got there, and the turning point is often the more useful fact --
    a company that has been Elevated for five years is a different situation
    from one that crossed last year.

    WHY IT IS HONEST

    Each point is computed from a TRUNCATED history: the rating for 2023 sees
    2021 to 2023 and nothing after. It is a genuine point-in-time rating, not
    hindsight applied backwards. That matters because several factors are
    trend-based, and letting them see future years would quietly leak
    information a reader would not have had.

    `compute_metrics` is passed in rather than imported to keep this module
    free of a circular dependency on metrics.py.
    """
    years = history.sorted_years()
    points: List[RatingPoint] = []

    # Two years is the minimum any trend factor can work with.
    for cut in range(2, len(years) + 1):
        window = years[:cut]
        shell = type(history)(
            ticker=history.ticker,
            company_name=history.company_name,
            years=list(window),
            currency=history.currency,
            units=history.units,
        )
        metrics = compute_metrics(shell)
        result = rate_stress(metrics, [(fy.year, fy.ebitda) for fy in window])
        points.append(RatingPoint(
            year=window[-1].year,
            rating=result.rating,
            score=result.score,
            max_score=result.max_score,
            ratio=result.ratio,
            assessed=result.assessed_count,
        ))
    return points


def trajectory_summary(points: List[RatingPoint]) -> str:
    """One sentence describing the path, naming any crossing."""
    if len(points) < 2:
        return "Not enough history to show how the rating has moved."

    first, last = points[0], points[-1]

    if first.rating == last.rating:
        # The band can stay the same while the score moves a long way inside
        # it. Reporting only the unchanged label would hide real
        # deterioration -- a company going from 69% to 85% of its stress
        # points has got materially worse without crossing a threshold.
        base = (f"The rating has been {last.rating.lower()} throughout the "
                f"period, from {first.year} to {last.year}")
        if first.ratio is not None and last.ratio is not None:
            shift = last.ratio - first.ratio
            if abs(shift) >= 0.10:
                direction = "worsened" if shift > 0 else "improved"
                return (base + f", though the underlying score has {direction} "
                        f"from {first.ratio:.0%} to {last.ratio:.0%} of the "
                        "assessable maximum.")
        return base + "."

    order = [LOW, MODERATE, ELEVATED]
    try:
        worsened = order.index(last.rating) > order.index(first.rating)
    except ValueError:
        worsened = False

    # The year it last changed is the turning point worth naming.
    crossing = next((points[i] for i in range(len(points) - 1, 0, -1)
                     if points[i].rating != points[i - 1].rating), None)
    when = f" It crossed in {crossing.year}." if crossing else ""

    direction = "deteriorated" if worsened else "improved"
    return (f"The rating has {direction} from {first.rating.lower()} in "
            f"{first.year} to {last.rating.lower()} in {last.year}.{when}")
