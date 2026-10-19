"""
Stage 2b: the warning signals.

Each signal is one simple question comparing the earliest year we have with
the latest. Nothing clever, nothing statistical -- just "did this get worse?"

THE INTERPRETIVE RULE OF THIS MODULE, and the thing to say out loud when you
present the project: no single signal means a company is in trouble.

Every signal here has an innocent explanation as well as a worrying one:
  - Debt rising?          Could be funding a profitable acquisition.
  - Negative FCF?         Could be a deliberate expansion programme.
  - Revenue falling?      Could be exiting a low-margin business on purpose.
  - Cash falling?         Could be a share buyback from a position of strength.

What matters is how many fire together, and whether they tell one coherent
story. Three signals pointing the same way -- earnings down, debt up, cash
down -- is a pattern worth investigating. One signal on its own is a question,
not an answer. This tool produces questions for an analyst, not verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .metrics import YearMetrics
from .models import FinancialHistory


@dataclass
class Signal:
    """One warning sign, evaluated.

    status is one of:
      "fired"   - the worrying condition is present
      "clear"   - we checked and the condition is not present
      "unknown" - we lacked the data to check, which is NOT the same as clear
    """

    name: str
    status: str
    detail: str
    why_it_matters: str

    @property
    def fired(self) -> bool:
        return self.status == "fired"


def _pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    """Percent change from old to new, as a decimal. None if not computable."""
    if old is None or new is None or old == 0:
        return None
    return (new - old) / abs(old)


def _fmt_money(value: Optional[float], units: str, currency: str) -> str:
    if value is None:
        return "n/a"
    return f"{currency} {value:,.0f}{'m' if units == 'millions' else ''}"


def evaluate_signals(history: FinancialHistory,
                     all_metrics: List[YearMetrics]) -> List[Signal]:
    """Check all seven warning signs across the available history."""
    years = history.sorted_years()
    signals: List[Signal] = []

    if len(years) < 2:
        return [
            Signal(
                name="Insufficient history",
                status="unknown",
                detail=f"Only {len(years)} year(s) of data available; trend "
                       "signals need at least two years.",
                why_it_matters="Trends, not levels, are what reveal "
                               "deterioration early.",
            )
        ]

    first, last = years[0], years[-1]
    first_m, last_m = all_metrics[0], all_metrics[-1]
    span = f"{first.year}-{last.year}"
    cur, units = history.currency, history.units

    def unknown(name: str, missing: str, why: str) -> Signal:
        return Signal(name, "unknown", f"Cannot assess: {missing} unavailable.", why)

    # --- 1. Revenue falling -------------------------------------------------
    why = ("Falling revenue flows into every other metric. EBITDA shrinks, so "
           "leverage rises and coverage falls even if the company borrows "
           "nothing more.")
    chg = _pct_change(first.revenue, last.revenue)
    if chg is None:
        signals.append(unknown("Revenue falling", "revenue", why))
    else:
        signals.append(Signal(
            "Revenue falling",
            "fired" if chg < 0 else "clear",
            f"Revenue moved {chg:+.1%} over {span} "
            f"({_fmt_money(first.revenue, units, cur)} to "
            f"{_fmt_money(last.revenue, units, cur)}).",
            why,
        ))

    # --- 2. EBITDA falling --------------------------------------------------
    why = ("EBITDA is the denominator of both leverage and coverage. When it "
           "falls, both ratios worsen at once -- which is why declining "
           "earnings is the single most common trigger of credit stress.")
    chg = _pct_change(first.ebitda, last.ebitda)
    if chg is None:
        signals.append(unknown("EBITDA falling", "EBITDA", why))
    else:
        signals.append(Signal(
            "EBITDA falling",
            "fired" if chg < 0 else "clear",
            f"EBITDA moved {chg:+.1%} over {span} "
            f"({_fmt_money(first.ebitda, units, cur)} to "
            f"{_fmt_money(last.ebitda, units, cur)}).",
            why,
        ))

    # --- 3. Debt increasing -------------------------------------------------
    why = ("Rising debt is not automatically bad -- it depends entirely on what "
           "the money bought. Debt funding a profitable acquisition is "
           "investment; debt funding an operating cash shortfall is a warning.")
    chg = _pct_change(first.total_debt, last.total_debt)
    if chg is None:
        signals.append(unknown("Debt increasing", "total debt", why))
    else:
        signals.append(Signal(
            "Debt increasing",
            "fired" if chg > 0 else "clear",
            f"Total debt moved {chg:+.1%} over {span} "
            f"({_fmt_money(first.total_debt, units, cur)} to "
            f"{_fmt_money(last.total_debt, units, cur)}).",
            why,
        ))

    # --- 4. Debt / EBITDA increasing ---------------------------------------
    why = ("This is the signal that combines signals 2 and 3. Leverage can "
           "rise from borrowing more, from earning less, or from both at once. "
           "It captures the net effect, which is what lenders actually watch.")
    if first_m.net_debt_to_ebitda is None or last_m.net_debt_to_ebitda is None:
        signals.append(unknown("Leverage (Net Debt/EBITDA) increasing",
                               "net debt or EBITDA", why))
    else:
        delta = last_m.net_debt_to_ebitda - first_m.net_debt_to_ebitda
        signals.append(Signal(
            "Leverage (Net Debt/EBITDA) increasing",
            "fired" if delta > 0 else "clear",
            f"Net Debt/EBITDA moved from {first_m.net_debt_to_ebitda:.2f}x to "
            f"{last_m.net_debt_to_ebitda:.2f}x over {span} ({delta:+.2f}x).",
            why,
        ))

    # --- 5. Interest coverage decreasing -----------------------------------
    why = ("Coverage is the most time-critical metric. Interest is due on fixed "
           "dates and missing a payment is an event of default, which can "
           "accelerate the whole loan. Falling coverage shortens the runway.")
    if first_m.interest_coverage is None or last_m.interest_coverage is None:
        signals.append(unknown("Interest coverage decreasing",
                               "EBITDA or interest expense", why))
    else:
        delta = last_m.interest_coverage - first_m.interest_coverage
        signals.append(Signal(
            "Interest coverage decreasing",
            "fired" if delta < 0 else "clear",
            f"Interest coverage moved from {first_m.interest_coverage:.2f}x to "
            f"{last_m.interest_coverage:.2f}x over {span} ({delta:+.2f}x).",
            why,
        ))

    # --- 6. Negative free cash flow ----------------------------------------
    why = ("Negative FCF means the company cannot fund itself. The gap must be "
           "filled from cash reserves, asset sales, or new borrowing. If it is "
           "filled with debt, leverage rises mechanically every year -- the "
           "slow spiral that leads most companies into distress.")
    if last_m.free_cash_flow is None:
        signals.append(unknown("Negative free cash flow",
                               "operating cash flow or capex", why))
    else:
        negative_years = [m.year for m in all_metrics
                          if m.free_cash_flow is not None and m.free_cash_flow < 0]
        fired = last_m.free_cash_flow < 0
        detail = (f"FCF in {last.year} was "
                  f"{_fmt_money(last_m.free_cash_flow, units, cur)}.")
        if negative_years:
            detail += (f" Negative in {len(negative_years)} of "
                       f"{len(all_metrics)} years: "
                       f"{', '.join(str(y) for y in negative_years)}.")
        signals.append(Signal("Negative free cash flow",
                              "fired" if fired else "clear", detail, why))

    # --- 7. Cash decreasing -------------------------------------------------
    why = ("Cash is the buffer that buys time. A company with problems and a "
           "large cash pile has room to fix them; the same company with no "
           "cash has to negotiate with its lenders instead.")
    chg = _pct_change(first.cash, last.cash)
    if chg is None:
        signals.append(unknown("Cash decreasing", "cash", why))
    else:
        signals.append(Signal(
            "Cash decreasing",
            "fired" if chg < 0 else "clear",
            f"Cash moved {chg:+.1%} over {span} "
            f"({_fmt_money(first.cash, units, cur)} to "
            f"{_fmt_money(last.cash, units, cur)}).",
            why,
        ))

    return signals
