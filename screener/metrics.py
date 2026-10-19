"""
The six credit metrics, one function each.

Every function here is pure: same inputs always give the same output, nothing
is fetched, nothing is printed, no global state. That makes them trivial to
test (see tests/test_metrics.py) and easy to explain in an interview.

Every function also returns None rather than raising when an input is missing
or a denominator is zero. In credit work "I cannot compute this" is a real and
useful answer, and it must not be confused with "the answer is zero".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import FinancialHistory, FiscalYear


# ---------------------------------------------------------------------------
# The one piece of shared plumbing
# ---------------------------------------------------------------------------

def safe_divide(numerator: Optional[float],
                denominator: Optional[float]) -> Optional[float]:
    """Divide, returning None instead of blowing up or lying.

    Returns None when:
      - either input is missing (None)
      - the denominator is zero (undefined)
      - the denominator is negative

    That last rule deserves explanation, because it is a genuine analytical
    judgement and not just defensive coding.

    If EBITDA is NEGATIVE, Debt / EBITDA is mathematically computable but
    financially meaningless. A company with $500m of debt and -$100m of EBITDA
    produces "-5.0x", which looks less leveraged than a healthy company at
    6.0x. It is in fact infinitely worse: the business is burning cash and no
    multiple of earnings can repay the debt, because there are no earnings.
    Returning None forces the report to say "not meaningful -- EBITDA is
    negative", which is the truthful answer. negative_denominator_reason()
    below supplies that wording.
    """
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


def negative_denominator_reason(denominator: Optional[float],
                                label: str = "EBITDA") -> Optional[str]:
    """Explain WHY a ratio came back None, when the cause was the denominator.

    The report calls this so a blank cell always carries a reason.
    """
    if denominator is None:
        return f"{label} not available"
    if denominator == 0:
        return f"{label} is zero"
    if denominator < 0:
        return f"not meaningful - {label} is negative"
    return None


# ---------------------------------------------------------------------------
# The six metrics
# ---------------------------------------------------------------------------

def net_debt(total_debt: Optional[float],
             cash: Optional[float]) -> Optional[float]:
    """Net Debt = Total Debt - Cash.

    The idea: cash on the balance sheet could be used to pay down borrowings
    tomorrow morning, so the company's *economic* debt burden is the gross
    borrowings minus the cash it already holds.

    Net debt can legitimately be negative -- that means the company holds more
    cash than debt, which is a strong position. We return it as-is; it is only
    when net debt is used as a NUMERATOR that negative values are fine.
    """
    if total_debt is None or cash is None:
        return None
    return total_debt - cash


def debt_to_ebitda(total_debt: Optional[float],
                   ebitda: Optional[float]) -> Optional[float]:
    """Debt / EBITDA -- the most quoted number in all of credit.

        Debt / EBITDA = Total Debt / EBITDA

    Read it as: "how many years of EBITDA would it take to repay all the
    debt, if every dollar of EBITDA went to repayment?"

    Rough market convention for a typical corporate:
        under 2.0x  conservative
        2.0 - 4.0x  normal for a leveraged but healthy business
        4.0 - 6.0x  genuinely leveraged, lenders are paying attention
        over 6.0x   stressed; refinancing becomes difficult and expensive

    These bands are conventions, not laws, and they vary a lot by industry.
    A regulated utility with predictable cash flows can carry 5x comfortably;
    a cyclical mining company at 5x is in trouble. Always compare a company
    to its own industry -- which is exactly what the peers.py extension is for.
    """
    return safe_divide(total_debt, ebitda)


def net_debt_to_ebitda(total_debt: Optional[float],
                       cash: Optional[float],
                       ebitda: Optional[float]) -> Optional[float]:
    """Net Debt / EBITDA.

        Net Debt / EBITDA = (Total Debt - Cash) / EBITDA

    The same question as Debt/EBITDA, but giving the company credit for the
    cash it already has. Because cash is subtracted, this is always lower
    than (or equal to) Debt/EBITDA, and it is generally the more realistic
    measure of the burden. Credit agreements are often written against it.

    Watch the gap between the two ratios. A big gap means a lot of the
    apparent leverage is offset by cash -- but ask whether that cash is
    genuinely available. Cash trapped in a foreign subsidiary, or needed for
    day-to-day operations, cannot actually repay debt. That is one of the
    things a real analyst would dig into.
    """
    nd = net_debt(total_debt, cash)
    return safe_divide(nd, ebitda)


def interest_coverage(ebitda: Optional[float],
                      interest_expense: Optional[float]) -> Optional[float]:
    """Interest Coverage = EBITDA / Interest Expense.

    Read it as: "how many times over can the company pay this year's
    interest bill out of this year's operating earnings?"

    Rough convention:
        over 6.0x    comfortable
        3.0 - 6.0x   adequate
        1.5 - 3.0x   tight; little room for a bad year
        under 1.5x   the company can barely afford its own debt

    Why this is the most URGENT metric of the set: leverage is a measure of
    size, but coverage is a measure of timing. High leverage is survivable for
    years if the interest is comfortably covered. But interest payments are
    due on fixed dates, and missing one is an event of default -- which can
    accelerate the entire loan and force a restructuring immediately. When
    coverage approaches 1.0x, the problem stops being theoretical.

    Note we use EBITDA over interest here for consistency with the leverage
    ratios. You will also see EBIT / Interest in practice, which is stricter
    (it subtracts depreciation first) and arguably more honest, since worn-out
    equipment does eventually have to be replaced with real cash.
    """
    return safe_divide(ebitda, interest_expense)


def free_cash_flow(operating_cash_flow: Optional[float],
                   capex: Optional[float]) -> Optional[float]:
    """Free Cash Flow = Operating Cash Flow - Capital Expenditure.

    (In this project capex is stored as a positive "money spent" number, so
    the subtraction reads exactly like the textbook formula.)

    This is the number that cuts through accounting. EBITDA is a profitability
    proxy that deliberately ignores the cost of maintaining the asset base.
    FCF does not: it is the cash genuinely left over after both running the
    business and keeping its equipment and stores in working order.

    Why it matters so much under stress: FCF answers "is this situation
    stable or deteriorating on its own?" A company with positive FCF can
    service debt and slowly repay it. A company with NEGATIVE FCF must find
    cash from somewhere else every single year -- draw down its cash pile, sell
    assets, or borrow more. The third option increases debt while the earnings
    that service it are not growing, so leverage rises mechanically, year
    after year, with no single dramatic event. That slow spiral -- negative FCF
    funded by rising debt -- is the most common path into distress.

    Unlike the ratios above, FCF is a dollar amount, and negative values are
    meaningful and important. So we do NOT use safe_divide here.
    """
    if operating_cash_flow is None or capex is None:
        return None
    return operating_cash_flow - capex


def ebitda_margin(ebitda: Optional[float],
                  revenue: Optional[float]) -> Optional[float]:
    """EBITDA Margin = EBITDA / Revenue. Returned as a DECIMAL (0.18 = 18%).

    How many cents of operating earnings the company keeps from each dollar
    of sales. Useful for two things:

      1. Comparing companies of very different sizes.
      2. Separating a volume problem from a profitability problem. If revenue
         is flat but margin is falling, the company is selling just as much
         and keeping less of it -- costs are rising faster than prices, or it
         is discounting to defend market share. Both are early warnings that
         usually show up before the leverage ratios react.
    """
    return safe_divide(ebitda, revenue)


def revenue_growth(current_revenue: Optional[float],
                   prior_revenue: Optional[float]) -> Optional[float]:
    """Revenue Growth = (Revenue_this_year / Revenue_last_year) - 1.

    Returned as a DECIMAL (-0.07 = revenue fell 7%).

    The top line. It matters first because it is the input to everything
    else -- falling revenue flows into falling EBITDA, which raises leverage
    and lowers coverage without any change in the debt at all. A company can
    become more leveraged while borrowing nothing, purely by shrinking.
    """
    if current_revenue is None or prior_revenue is None:
        return None
    if prior_revenue <= 0:
        return None
    return (current_revenue / prior_revenue) - 1.0


# ---------------------------------------------------------------------------
# Applying all six to a whole history
# ---------------------------------------------------------------------------

@dataclass
class YearMetrics:
    """All computed metrics for a single fiscal year.

    `reasons` explains any metric that came out None, keyed by metric name,
    so the report never shows an unexplained blank.
    """

    year: int
    net_debt: Optional[float] = None
    debt_to_ebitda: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    free_cash_flow: Optional[float] = None
    ebitda_margin: Optional[float] = None
    revenue_growth: Optional[float] = None
    reasons: Dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = {}


def compute_year_metrics(fy: FiscalYear,
                         prior: Optional[FiscalYear] = None) -> YearMetrics:
    """Compute all six metrics for one year.

    `prior` is the immediately preceding year, needed only for revenue growth
    (which is a year-over-year comparison, so the first year in any dataset
    will always have revenue_growth = None -- that is correct, not a bug).
    """
    m = YearMetrics(year=fy.year)

    m.net_debt = net_debt(fy.total_debt, fy.cash)
    m.debt_to_ebitda = debt_to_ebitda(fy.total_debt, fy.ebitda)
    m.net_debt_to_ebitda = net_debt_to_ebitda(fy.total_debt, fy.cash, fy.ebitda)
    m.interest_coverage = interest_coverage(fy.ebitda, fy.interest_expense)
    m.free_cash_flow = free_cash_flow(fy.operating_cash_flow, fy.capex)
    m.ebitda_margin = ebitda_margin(fy.ebitda, fy.revenue)
    m.revenue_growth = revenue_growth(
        fy.revenue, prior.revenue if prior else None
    )

    # Record why anything is blank, so the report can explain itself.
    if m.debt_to_ebitda is None:
        reason = negative_denominator_reason(fy.ebitda, "EBITDA")
        m.reasons["debt_to_ebitda"] = reason or "Total Debt not available"
    if m.net_debt_to_ebitda is None:
        reason = negative_denominator_reason(fy.ebitda, "EBITDA")
        m.reasons["net_debt_to_ebitda"] = reason or "Total Debt or Cash not available"
    if m.interest_coverage is None:
        reason = negative_denominator_reason(fy.interest_expense, "Interest expense")
        m.reasons["interest_coverage"] = reason or "EBITDA not available"
    if m.free_cash_flow is None:
        m.reasons["free_cash_flow"] = "Operating cash flow or capex not available"
    if m.ebitda_margin is None:
        m.reasons["ebitda_margin"] = "EBITDA or revenue not available"
    if m.revenue_growth is None and prior is not None:
        m.reasons["revenue_growth"] = "Revenue not available for both years"

    return m


def compute_all_metrics(history: FinancialHistory) -> List[YearMetrics]:
    """Compute metrics for every year in the history, oldest-first."""
    years = history.sorted_years()
    out: List[YearMetrics] = []
    for i, fy in enumerate(years):
        prior = years[i - 1] if i > 0 else None
        out.append(compute_year_metrics(fy, prior))
    return out
