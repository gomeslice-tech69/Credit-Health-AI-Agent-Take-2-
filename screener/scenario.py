"""
Stage 2c: one simple downside scenario.

The question: what happens to the credit metrics if EBITDA falls by 20%?

WHY THIS IS THE RIGHT FIRST SCENARIO TO BUILD

A single year's ratios tell you where a company stands today. They do not tell
you how much room it has before it has a real problem. That second question is
often the more important one, and it is what a stress test answers.

The mechanics are worth understanding because they are the core of why
leverage is dangerous. Debt does not shrink when business gets worse -- it is a
fixed claim. Interest does not fall either. So when EBITDA drops 20%:

  - Debt / EBITDA rises by 1 / 0.8 = 25%, not 20%. The numerator is unchanged
    and the denominator shrank, so the ratio moves more than the input did.
  - Interest coverage falls by the same 25% proportion, for the same reason.

This asymmetry -- earnings fall by X, leverage rises by more than X -- is
precisely what makes a leveraged company fragile. A business with no debt that
loses 20% of its earnings has a disappointing year. A business at 5x leverage
that loses 20% of its earnings is at 6.25x and may have breached a covenant.

Why 20%: it is roughly a normal cyclical downturn for an average business --
bad, but not catastrophic. It is deliberately a plain, defensible number you
can justify in one sentence. Change it with --scenario if you want.

WHAT THIS SCENARIO DELIBERATELY DOES NOT DO: in a real downturn, cash and
working capital move too, capex gets cut, and the company may draw on a credit
line. Holding everything else constant isolates the single effect of lower
earnings, which makes the result easy to interpret. It is a sensitivity test,
not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import metrics as M
from .metrics import YearMetrics
from .models import FiscalYear


@dataclass
class ScenarioResult:
    """Before-and-after comparison for one downside case."""

    label: str
    haircut: float               # 0.20 means EBITDA falls 20%
    base_ebitda: Optional[float]
    stressed_ebitda: Optional[float]
    base: YearMetrics
    stressed: YearMetrics
    meaningful: bool = True      # False when the scenario cannot be applied
    note: str = ""               # explanation when meaningful is False

    def delta(self, metric_name: str) -> Optional[float]:
        """Change in a metric from base to stressed case."""
        before = getattr(self.base, metric_name)
        after = getattr(self.stressed, metric_name)
        if before is None or after is None:
            return None
        return after - before


def run_ebitda_downside(fy: FiscalYear,
                        prior: Optional[FiscalYear] = None,
                        haircut: float = 0.20) -> ScenarioResult:
    """Cut EBITDA by `haircut` and recompute the three ratios it drives.

    Deliberately held CONSTANT: debt, cash, interest expense, revenue.
    Deliberately recomputed: Debt/EBITDA, Net Debt/EBITDA, Interest Coverage.

    Note that free cash flow is NOT recomputed. FCF is built from operating
    cash flow and capex, and this scenario makes no assumption about how a
    20% EBITDA decline would translate into either. Guessing at that link
    would be inventing data, so we leave FCF out of the scenario entirely.
    """
    if not 0 <= haircut < 1:
        raise ValueError(f"haircut must be between 0 and 1, got {haircut}")

    base = M.compute_year_metrics(fy, prior)

    # GUARD: this scenario only makes sense when EBITDA is positive.
    #
    # Multiplying a NEGATIVE EBITDA by 0.8 makes it less negative -- -120
    # becomes -96 -- so the arithmetic would show the stressed case as an
    # IMPROVEMENT. That is obviously wrong, and it is the kind of sign error
    # that silently produces a confident, backwards answer.
    #
    # We could pick a convention for negative EBITDA (multiply by 1.2 to deepen
    # the loss, say), but any choice would be ours rather than the data's. For
    # a company already losing money at the EBITDA level, "what if earnings
    # fell 20%?" is also the wrong question: it is already in distress by this
    # measure, and the live question is how long its cash lasts. So we decline
    # to run the scenario and say why.
    if fy.ebitda is not None and fy.ebitda <= 0:
        return ScenarioResult(
            label=f"EBITDA falls {haircut:.0%}",
            haircut=haircut,
            base_ebitda=fy.ebitda,
            stressed_ebitda=None,
            base=base,
            stressed=base,
            meaningful=False,
            note=("This scenario was not run. EBITDA in the latest year was "
                  f"{fy.ebitda:,.0f}, which is not positive. Applying a "
                  "percentage decline to a negative number would make it "
                  "smaller in magnitude and so would wrongly appear as an "
                  "improvement. For a company already generating negative "
                  "EBITDA the relevant question is not a further earnings "
                  "decline but liquidity: how much cash is on hand, how fast "
                  "it is being consumed, and how long that leaves."),
        )

    stressed_ebitda = None if fy.ebitda is None else fy.ebitda * (1.0 - haircut)

    stressed_fy = FiscalYear(
        year=fy.year,
        revenue=fy.revenue,
        ebitda=stressed_ebitda,
        interest_expense=fy.interest_expense,   # unchanged: a fixed claim
        cash=fy.cash,                           # unchanged: held constant
        total_debt=fy.total_debt,               # unchanged: does not shrink
        operating_cash_flow=fy.operating_cash_flow,
        capex=fy.capex,
    )
    stressed = M.compute_year_metrics(stressed_fy, prior)

    return ScenarioResult(
        label=f"EBITDA falls {haircut:.0%}",
        haircut=haircut,
        base_ebitda=fy.ebitda,
        stressed_ebitda=stressed_ebitda,
        base=base,
        stressed=stressed,
    )
