"""
The Altman Z''-score: an independent, published check on our own rating.

WHY INCLUDE A SECOND OPINION

The five-factor rating in rating.py is this project's own invention. Its
thresholds are defensible credit conventions, but nobody has validated them
against real outcomes. The Altman Z-score has been in use since 1968, is
taught in every corporate finance course, and was fitted against companies
that actually did and did not fail.

Running both and showing them side by side is more honest than either alone:

  * They agree -> two different methods reached the same view, which is
    reassuring.
  * They disagree -> interesting, and the reason is usually instructive. They
    measure different things, so disagreement is information rather than error.

WHAT THE TWO MEASURE, AND WHY THEY CAN DIFFER

Our rating is a DEBT-SERVICE measure. It asks whether this company can keep
paying what it owes: leverage, interest coverage, cash generation, earnings
direction.

The Z-score is a BALANCE-SHEET measure. It asks whether the company has
accumulated enough value to absorb losses: working capital, lifetime retained
profit, asset productivity, equity cushion.

A company can service its debt comfortably while having a thin balance sheet
(stable cash flow, little accumulated equity), or have a strong balance sheet
while struggling to make payments (asset-rich, cash-poor). Each measure catches
something the other misses.

WHICH VARIANT, AND WHY

Altman published several. This uses **Z''**, the four-variable version:

    Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4

    X1 = Working Capital / Total Assets      short-term liquidity cushion
    X2 = Retained Earnings / Total Assets    lifetime accumulated profit
    X3 = EBIT / Total Assets                 how productively assets earn
    X4 = Book Equity / Total Liabilities     the loss-absorbing cushion

The original 1968 Z-score includes a fifth term (Sales / Total Assets) and
uses the MARKET value of equity. Z'' drops both, which matters here for two
practical reasons: it needs no share-price data, and the sales-to-assets term
varies so much between industries that the original Z is really only valid for
manufacturers. Z'' was designed to work across industries.

The coefficients are Altman's published values. Nothing here is fitted by this
project -- that is the point of using an external model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import FiscalYear

# Altman's published Z'' coefficients. Do not tune these: their authority
# comes entirely from being the published values rather than ours.
W_WORKING_CAPITAL = 6.56
W_RETAINED_EARNINGS = 3.26
W_EBIT = 6.72
W_EQUITY = 1.05

# Altman's published Z'' cut-offs.
SAFE_ABOVE = 2.6
DISTRESS_BELOW = 1.1

SAFE = "Safe zone"
GREY = "Grey zone"
DISTRESS = "Distress zone"
UNAVAILABLE = "Not computable"


@dataclass
class ZScore:
    """One year's Z''-score, with every component kept for inspection."""

    year: int
    score: Optional[float] = None
    zone: str = UNAVAILABLE
    reason: str = ""
    working_capital_ratio: Optional[float] = None
    retained_earnings_ratio: Optional[float] = None
    ebit_ratio: Optional[float] = None
    equity_ratio: Optional[float] = None
    missing: Optional[List[str]] = None

    @property
    def available(self) -> bool:
        return self.score is not None


def zone_for(score: Optional[float]) -> str:
    """Map a score to Altman's published bands."""
    if score is None:
        return UNAVAILABLE
    if score > SAFE_ABOVE:
        return SAFE
    if score < DISTRESS_BELOW:
        return DISTRESS
    return GREY


def compute_z_score(fy: FiscalYear) -> ZScore:
    """Compute Z'' for one fiscal year.

    Returns a ZScore whose `score` is None, with a stated `reason`, whenever
    the inputs do not support a meaningful answer. The same rule as everywhere
    else in this project: refuse rather than guess.
    """
    result = ZScore(year=fy.year)

    required = {
        "total assets": fy.total_assets,
        "current assets": fy.current_assets,
        "current liabilities": fy.current_liabilities,
        "retained earnings": fy.retained_earnings,
        "operating income (EBIT)": fy.operating_income,
        "total liabilities": fy.total_liabilities,
        "shareholders' equity": fy.shareholders_equity,
    }
    missing = sorted(name for name, value in required.items() if value is None)
    if missing:
        result.missing = missing
        result.reason = (
            "Needs the full balance sheet. Not available: "
            + ", ".join(missing) + ".")
        return result

    if fy.total_assets <= 0:
        result.reason = "Total assets are not positive, so the ratios are undefined."
        return result
    if fy.total_liabilities <= 0:
        result.reason = (
            "Total liabilities are not positive. A company with no liabilities "
            "has no solvency question for this model to answer.")
        return result

    working_capital = fy.current_assets - fy.current_liabilities

    result.working_capital_ratio = working_capital / fy.total_assets
    result.retained_earnings_ratio = fy.retained_earnings / fy.total_assets
    result.ebit_ratio = fy.operating_income / fy.total_assets
    result.equity_ratio = fy.shareholders_equity / fy.total_liabilities

    result.score = (
        W_WORKING_CAPITAL * result.working_capital_ratio
        + W_RETAINED_EARNINGS * result.retained_earnings_ratio
        + W_EBIT * result.ebit_ratio
        + W_EQUITY * result.equity_ratio
    )
    result.zone = zone_for(result.score)
    return result


def compute_all_z_scores(years: List[FiscalYear]) -> List[ZScore]:
    """Compute Z'' for every year, oldest first."""
    return [compute_z_score(fy) for fy in sorted(years, key=lambda y: y.year)]


def components(z: ZScore) -> List[dict]:
    """The four terms with their weights and contributions, for display.

    Showing the contribution of each term is what makes the score explainable:
    a reader can see which part of the balance sheet drove the result instead
    of being handed a bare number.
    """
    if not z.available:
        return []
    rows = [
        ("Working capital / assets", z.working_capital_ratio,
         W_WORKING_CAPITAL,
         "Short-term cushion: current assets less current liabilities. "
         "Negative means short-term bills exceed short-term resources."),
        ("Retained earnings / assets", z.retained_earnings_ratio,
         W_RETAINED_EARNINGS,
         "Lifetime accumulated profit. Negative means the company has lost "
         "more over its life than it has earned."),
        ("EBIT / assets", z.ebit_ratio, W_EBIT,
         "How productively the asset base generates operating profit."),
        ("Equity / liabilities", z.equity_ratio, W_EQUITY,
         "The loss-absorbing cushion. Negative means liabilities exceed "
         "assets, so the equity has been wiped out."),
    ]
    return [{"label": label, "ratio": ratio, "weight": weight,
             "contribution": ratio * weight, "explanation": explanation}
            for label, ratio, weight, explanation in rows]


def interpretation(z: ZScore) -> str:
    """One paragraph explaining the result, and what it does not mean."""
    if not z.available:
        return z.reason

    if z.zone == SAFE:
        verdict = (
            f"At {z.score:.2f}, the score sits above Altman's 2.6 threshold, "
            "in what he called the safe zone. The balance sheet carries enough "
            "accumulated value and working capital to absorb a setback.")
    elif z.zone == DISTRESS:
        verdict = (
            f"At {z.score:.2f}, the score sits below Altman's 1.1 threshold, "
            "in what he called the distress zone. Historically, companies "
            "scoring here have been far more likely to run into serious "
            "financial difficulty.")
    else:
        verdict = (
            f"At {z.score:.2f}, the score falls between Altman's thresholds of "
            "1.1 and 2.6 — the grey zone, where the model does not give a "
            "clear signal either way.")

    return verdict + (
        " This is a published model from 1968, not a calculation of this "
        "project's own, and it was fitted on a small sample of companies of "
        "its era. Treat it as a second opinion that measures the balance "
        "sheet, where the main rating measures debt service. It is not a "
        "prediction of bankruptcy."
    )


def is_meaningful_for(sector: Optional[str]) -> tuple:
    """Whether Z'' should be shown for this kind of company.

    Returns (meaningful, reason).

    Banks and insurers are excluded deliberately. Their balance sheets are
    structurally different -- deposits and policy reserves are liabilities in a
    sense that has nothing to do with solvency risk, and working capital is not
    a meaningful concept for them. Altman's model was never fitted on financial
    firms, and applying it to one produces a confident number that means
    nothing.
    """
    if not sector:
        return True, ""
    lowered = sector.lower()
    if any(word in lowered for word in
           ("financial", "bank", "insurance", "capital market")):
        return False, (
            f"The Z-score is not shown for {sector} companies. Altman's model "
            "was fitted on industrial and commercial firms, and a financial "
            "institution's balance sheet works differently enough that the "
            "ratios do not carry the same meaning.")
    return True, ""
