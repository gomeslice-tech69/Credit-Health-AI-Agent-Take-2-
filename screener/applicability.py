"""
Whether this framework applies to a company at all.

THE PROBLEM THIS SOLVES

The six credit metrics assume an industrial or commercial business: one that
sells things, borrows to fund itself, and services that borrowing out of
operating earnings. Debt is a financing choice, interest is the cost of that
choice, and EBITDA approximates the cash available to pay it.

For a bank none of that holds. A bank borrows in order to lend -- deposits and
wholesale funding are its raw material, not its capital structure. Interest
expense is closer to cost of goods sold than to a financing cost, so "earnings
before interest" strips out the main input. Goldman Sachs reports $66.8bn of
interest expense against $58.3bn of revenue; that is not distress, it is what
the business does.

Run the framework anyway and it produces a number. Goldman's operating cash
flow of -$45bn scores three of three stress points for "a sustained cash
shortfall", when it actually reflects a growing loan book. A confident wrong
answer is worse than no answer, which is why this module exists.

WHAT IT DOES

Classifies a company as FULL, PARTIAL or NOT_APPLICABLE, and says why. The
screener refuses to rate anything not applicable, and warns on partial.

Classification is by reported sector and industry, which is crude but
transparent. It will occasionally misjudge a conglomerate. The alternative --
inferring from the numbers -- would be silently wrong instead of visibly
approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FULL = "full"
PARTIAL = "partial"
NOT_APPLICABLE = "not_applicable"


@dataclass
class Applicability:
    """Whether and how far the framework applies."""

    level: str
    headline: str
    detail: str

    @property
    def can_rate(self) -> bool:
        return self.level != NOT_APPLICABLE

    @property
    def is_full(self) -> bool:
        return self.level == FULL


# Sectors and industries where leverage and coverage do not carry their usual
# meaning. Matching is on lowercase substrings of whatever the data source
# reports, which varies between sources.
_FINANCIAL = (
    "financial services", "financial conglomerate", "bank", "banks",
    "insurance", "capital market", "asset management",
    "credit services", "mortgage", "savings", "thrift",
)
_REIT = ("reit", "real estate investment")
_UTILITY = ("utilit", "regulated electric", "regulated gas", "regulated water")


def _contains(text: Optional[str], needles) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(n in lowered for n in needles)


def assess(sector: Optional[str], industry: Optional[str]) -> Applicability:
    """Decide whether the credit framework applies to this kind of company."""

    if _contains(sector, _FINANCIAL) or _contains(industry, _FINANCIAL):
        return Applicability(
            level=NOT_APPLICABLE,
            headline="This framework does not apply to financial companies.",
            detail=(
                "Banks, insurers and asset managers borrow in order to lend "
                "or underwrite. Deposits and wholesale funding are raw "
                "material, not capital structure, so interest expense sits "
                "closer to cost of goods sold than to a financing cost — "
                "Goldman Sachs reports more interest expense than revenue, "
                "which is normal rather than alarming.\n\n"
                "That breaks every ratio here. EBITDA is not reported because "
                "earnings before interest is not a meaningful quantity. "
                "Operating cash flow swings with the loan book rather than "
                "with profitability. Debt is funding, not leverage.\n\n"
                "Financial institutions are analysed with a different "
                "toolkit: regulatory capital ratios such as CET1, net "
                "interest margin, loan loss provisions and liquidity coverage. "
                "None of those are computed here, so no rating is produced."),
        )

    if _contains(sector, _REIT) or _contains(industry, _REIT):
        return Applicability(
            level=PARTIAL,
            headline="Treat these figures with care — this is a REIT.",
            detail=(
                "Real estate trusts carry high leverage by design and fund "
                "long-lived assets with long-dated debt, so a multiple that "
                "would alarm in manufacturing can be routine here.\n\n"
                "Depreciation is also large and largely non-economic for "
                "property, which is why the industry reports funds from "
                "operations rather than earnings. EBITDA-based ratios are "
                "used for REITs, but read them against REIT norms rather "
                "than the general thresholds this tool applies."),
        )

    if _contains(sector, _UTILITY) or _contains(industry, _UTILITY):
        return Applicability(
            level=PARTIAL,
            headline="Read these thresholds against utility norms.",
            detail=(
                "Regulated utilities run higher leverage than the general "
                "thresholds assume, and do so safely: cash flows are "
                "contracted or rate-regulated, and the asset base is long "
                "lived. Four to five times leverage is ordinary here and "
                "would be a warning in a cyclical business.\n\n"
                "The metrics are computed correctly. It is the bands that are "
                "calibrated for industrials, which is exactly what the sector "
                "comparison is for."),
        )

    return Applicability(
        level=FULL,
        headline="",
        detail="",
    )


def summary_line(applicability: Applicability) -> str:
    """One line for a table or a list, where the full detail will not fit."""
    return {
        FULL: "Framework applies",
        PARTIAL: "Applies with caveats",
        NOT_APPLICABLE: "Not applicable",
    }[applicability.level]
