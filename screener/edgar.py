"""
SEC EDGAR data source: official filings instead of a scraped aggregator.

WHY THIS EXISTS ALONGSIDE YAHOO FINANCE

Yahoo is convenient and needs no setup, but it is an unofficial scraper: row
labels drift between versions, line items go missing without warning, and
nothing about it is guaranteed. EDGAR is the opposite trade:

  * It is the actual regulatory filing, not a copy of one.
  * Figures carry standardised XBRL tags, so the same concept has the same
    name across every US filer. That is what makes large-scale comparison
    possible at all.
  * No API key, no quota, and no commercial terms to worry about.

The cost is that raw filings are messier than a cleaned feed. Companies choose
among several valid tags for the same concept, restate prior years, and file
overlapping periods. This module absorbs that mess so the rest of the project
does not have to.

SETUP

The SEC requires every automated request to identify its sender, and refuses
with HTTP 403 otherwise. Set a contact string before using this source:

    export SEC_USER_AGENT="Your Name your.email@example.com"

On Streamlit Community Cloud it goes in the app's Secrets panel. Use a real
address you monitor -- that is the condition of access, and the SEC will
contact you rather than simply block you if your traffic causes a problem.

See https://www.sec.gov/os/webmaster-faq#developers for the access policy.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .models import (FinancialHistory, FiscalYear, MaturityBucket,
                     MaturitySchedule)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# The SEC asks for no more than 10 requests a second. This module makes at most
# two per company, so a courteous gap costs nothing and keeps us well inside it.
_MIN_REQUEST_GAP = 0.15
_last_request_at = 0.0


class EdgarError(Exception):
    """Raised for any EDGAR problem. data_loader converts it to a
    DataLoadError so callers handle one exception type."""


# ---------------------------------------------------------------------------
# XBRL tag preferences
#
# Filers may choose among several valid tags for the same concept, so each
# field lists candidates in order of preference and the first one present wins.
# This is the part most likely to need extending as you meet new companies:
# add a tag to the relevant list rather than changing any logic.
# ---------------------------------------------------------------------------

REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
OPERATING_INCOME_TAGS = ["OperatingIncomeLoss"]

# Some filers (IBM, Pfizer) never tag OperatingIncomeLoss. For them EBIT is
# rebuilt from pre-tax income plus interest expense -- which is the definition
# of EBIT, read backwards. Both inputs are reported figures.
PRETAX_INCOME_TAGS = [
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
]
DEPRECIATION_TAGS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationAndAmortization",
    "Depreciation",
]
# "InterestExpense" was retired for most filers in favour of
# "InterestExpenseNonoperating", so both appear here and are merged by period:
# older years come from the first, recent years from the second.
INTEREST_TAGS = [
    "InterestExpense",
    "InterestExpenseNonoperating",
    "InterestExpenseDebt",
    "InterestAndDebtExpense",
    # Net interest tags: income netted against expense, so the figure can be
    # negative. The loader takes the absolute value, which treats it as net
    # interest cost. Delta and several others tag nothing else.
    "InterestIncomeExpenseNonoperatingNet",
    "InterestIncomeExpenseNet",
    # Cash interest actually paid, from the cash flow statement. A last resort
    # and not identical to accrued interest expense, but far closer than
    # leaving coverage uncomputable.
    "InterestPaidNet",
]
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherProductiveAssets",
    "PaymentsForCapitalImprovements",
]
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
# Debt is reported in pieces and filers differ on which pieces they tag, so
# both lists are merged by period (see _annual_series). Finance-lease
# obligations are included: credit analysis treats them as debt, because they
# are fixed contractual payment obligations like any borrowing.
LONG_TERM_DEBT_TAGS = [
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtNoncurrent",
    "LongTermDebt",
]
# Extended balance-sheet set, used only by the Altman Z''-score.
TOTAL_ASSETS_TAGS = ["Assets"]
CURRENT_ASSETS_TAGS = ["AssetsCurrent"]
CURRENT_LIABILITIES_TAGS = ["LiabilitiesCurrent"]
RETAINED_EARNINGS_TAGS = ["RetainedEarningsAccumulatedDeficit"]
TOTAL_LIABILITIES_TAGS = ["Liabilities"]
EQUITY_TAGS = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]

CURRENT_DEBT_TAGS = [
    "LongTermDebtAndCapitalLeaseObligationsCurrent",
    "LongTermDebtCurrent",
    "DebtCurrent",
]

# The maturity ladder, near to far. Filers tag each rung separately, and the
# capital-lease variants are merged in because finance leases are debt for
# credit purposes. A rung nobody tagged stays None rather than becoming zero.
MATURITY_BUCKETS = [
    ("Within 1 year", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
    ]),
    ("Year 2", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalInYearTwo",
    ]),
    ("Year 3", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalInYearThree",
    ]),
    ("Year 4", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalInYearFour",
    ]),
    ("Year 5", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalInYearFive",
    ]),
    ("After 5 years", [
        "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",
        "LongTermDebtAndCapitalLeaseObligationsMaturitiesRepaymentsOfPrincipalAfterYearFive",
    ]),
]

# A reported period counts as a full year within this many days. Fiscal years
# are 52 or 53 weeks, so they are not all exactly 365 days long.
_MIN_YEAR_DAYS = 330
_MAX_YEAR_DAYS = 400


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def user_agent() -> str:
    """The contact string the SEC requires, from SEC_USER_AGENT.

    Deliberately not defaulted to anything. The SEC's access policy asks for a
    real contact address, and silently sending an invented one on a user's
    behalf would be both rude and a good way to get an IP range blocked.
    """
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    if not ua:
        raise EdgarError(
            "SEC EDGAR requires you to identify yourself on every request, and "
            "refuses anonymous ones.\n\n"
            "Set a contact string before using this source:\n"
            '    export SEC_USER_AGENT="Your Name your.email@example.com"\n\n'
            "On Streamlit Community Cloud, add it in the app's Secrets panel. "
            "Use a real address you monitor — that is the condition of access.")
    if "@" not in ua:
        raise EdgarError(
            f"SEC_USER_AGENT must include a contact email address, e.g. "
            f'"Your Name your.email@example.com". Current value: {ua!r}')
    return ua


def _get_json(url: str, timeout: int = 60) -> Any:
    """Fetch and decode one JSON document, pacing requests politely."""
    global _last_request_at

    gap = time.monotonic() - _last_request_at
    if gap < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - gap)

    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent(),
                      "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            _last_request_at = time.monotonic()
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        _last_request_at = time.monotonic()
        if exc.code == 403:
            raise EdgarError(
                "The SEC rejected the request (403). This almost always means "
                "SEC_USER_AGENT is missing or does not contain a real contact "
                "email address.")
        if exc.code == 404:
            raise EdgarError(
                "The SEC has no XBRL data at that address (404). The company "
                "may not file with the SEC, or may be too small or too recent "
                "to have structured filings.")
        if exc.code == 429:
            raise EdgarError(
                "The SEC is rate-limiting this connection (429). Wait a "
                "minute and try again.")
        raise EdgarError(f"The SEC returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise EdgarError(f"Could not reach the SEC: {exc.reason}")
    except json.JSONDecodeError:
        raise EdgarError("The SEC returned something that was not valid JSON.")


# ---------------------------------------------------------------------------
# Ticker -> CIK
# ---------------------------------------------------------------------------

_ticker_map_cache: Optional[Dict[str, Dict[str, Any]]] = None


def ticker_to_cik(ticker: str) -> Tuple[int, str]:
    """Resolve a ticker to its SEC CIK number and registered company name.

    The SEC keys everything by CIK, not by ticker, so this lookup is required
    before anything else. The map covers about ten thousand filers and is held
    for the life of the process, since it changes rarely.
    """
    global _ticker_map_cache

    if _ticker_map_cache is None:
        data = _get_json(TICKER_MAP_URL)
        if not isinstance(data, dict):
            raise EdgarError("The SEC ticker map was not in the expected form.")
        _ticker_map_cache = {
            str(row["ticker"]).upper(): row
            for row in data.values()
            if isinstance(row, dict) and row.get("ticker")
        }

    row = _ticker_map_cache.get(ticker.upper())
    if row is None:
        raise EdgarError(
            f"'{ticker.upper()}' is not in the SEC's ticker list. EDGAR covers "
            "companies that file with the SEC, so foreign issuers without a US "
            "listing, funds and private companies will not appear. Try the "
            "Yahoo Finance source for those.")
    return int(row["cik_str"]), str(row.get("title") or ticker.upper())


# ---------------------------------------------------------------------------
# Extracting annual figures from the fact soup
# ---------------------------------------------------------------------------

def _is_full_year(fact: Dict[str, Any]) -> bool:
    """True when a duration fact covers a whole fiscal year rather than a
    quarter. Both are mixed together in the same list."""
    start, end = fact.get("start"), fact.get("end")
    if not start or not end:
        return False
    try:
        span = (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days
    except ValueError:
        return False
    return _MIN_YEAR_DAYS <= span <= _MAX_YEAR_DAYS


def _annual_series(gaap: Dict[str, Any], tags: List[str],
                   instant: bool) -> Tuple[Dict[str, float], List[str]]:
    """Pull one field's annual history out of the filings.

    Returns ({period_end_date: value}, tags_actually_used).

    Three subtleties this handles, each of which produces wrong numbers if
    ignored:

    1. TAGS GO STALE. Companies change which tag they use as accounting
       standards evolve. American Airlines last reported
       LongTermDebtNoncurrent in 2012 and has used LongTermDebt since. Taking
       the first tag that has *any* data would return a series ending in 2012
       and leave every recent year blank. So the candidates are MERGED by
       period: for each year, the value comes from the highest-preference tag
       that actually covers that year.

    2. DUPLICATE PERIODS. Every 10-K restates the prior year alongside the
       current one, so the same fiscal year appears in several filings. We keep
       the most recently FILED value, which is the company's latest word on
       that period and reflects any restatement.

    3. QUARTERS MIXED WITH YEARS. For income-statement and cash-flow items the
       same tag carries quarterly and annual facts together, distinguished only
       by the length of the period. Treating a quarter as a year would
       understate revenue roughly fourfold.

    Balance-sheet items are instants with no start date, so they need neither
    the length check nor a period concept -- hence the `instant` flag.
    """
    merged: Dict[str, float] = {}
    used: List[str] = []

    for tag in tags:
        entry = gaap.get(tag)
        if not entry:
            continue
        facts = entry.get("units", {}).get("USD")
        if not facts:
            continue

        best: Dict[str, Dict[str, Any]] = {}
        for fact in facts:
            if fact.get("form") not in ("10-K", "10-K/A"):
                continue
            if instant:
                if "start" in fact:
                    continue
            elif not _is_full_year(fact):
                continue

            end = fact.get("end")
            value = fact.get("val")
            if not end or value is None:
                continue

            previous = best.get(end)
            if previous is None or str(fact.get("filed", "")) >= str(
                    previous.get("filed", "")):
                best[end] = fact

        # Only fill periods no higher-preference tag already covered.
        added = False
        for end, fact in best.items():
            if end not in merged:
                merged[end] = float(fact["val"])
                added = True
        if added:
            used.append(tag)

    return merged, used


def _sum_series(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    """Add two series by period, keeping a period present in either one.

    Used for total debt, where long-term and current portions are reported
    separately and a company may report only one of them.
    """
    return {end: a.get(end, 0.0) + b.get(end, 0.0)
            for end in set(a) | set(b)}


# ---------------------------------------------------------------------------
# The loader
# ---------------------------------------------------------------------------

def _maturity_schedule(gaap: Dict[str, Any], as_of: str,
                       scale: float) -> Optional[MaturitySchedule]:
    """Read the debt maturity ladder as of one balance-sheet date.

    Returns None when the filing tags no rungs at all, which is common for
    companies whose debt is immaterial. A partially tagged ladder is returned
    with the untagged rungs left None -- showing four of six rungs is useful,
    and silently calling the other two zero would not be.
    """
    buckets: List[MaturityBucket] = []
    used: List[str] = []

    for label, tags in MATURITY_BUCKETS:
        amount = None
        for tag in tags:
            series, got = _annual_series(gaap, [tag], instant=True)
            if as_of in series:
                amount = series[as_of] / scale
                used.extend(got)
                break
        buckets.append(MaturityBucket(label=label, amount=amount))

    if all(b.amount is None for b in buckets):
        return None
    return MaturitySchedule(as_of_year=int(as_of[:4]), buckets=buckets,
                            tags_used=sorted(set(used)))


def load_edgar_history(ticker: str, max_years: int = 5) -> FinancialHistory:
    """Build a FinancialHistory from the company's SEC filings.

    Figures are converted to millions to match the rest of the project, and
    anything the filings do not contain stays None.
    """
    cik, registered_name = ticker_to_cik(ticker)
    facts = _get_json(COMPANY_FACTS_URL.format(cik=cik))

    gaap = (facts.get("facts") or {}).get("us-gaap")
    if not gaap:
        raise EdgarError(
            f"The SEC holds no us-gaap XBRL facts for {ticker.upper()}. This "
            "happens with foreign filers reporting under IFRS and with very "
            "small companies.")

    notes: Dict[str, str] = {}

    revenue, revenue_tags = _annual_series(gaap, REVENUE_TAGS, instant=False)
    operating_income, _ = _annual_series(gaap, OPERATING_INCOME_TAGS, instant=False)
    depreciation, dep_tags = _annual_series(gaap, DEPRECIATION_TAGS, instant=False)
    interest, _ = _annual_series(gaap, INTEREST_TAGS, instant=False)
    ocf, _ = _annual_series(gaap, OCF_TAGS, instant=False)
    capex, _ = _annual_series(gaap, CAPEX_TAGS, instant=False)
    cash, _ = _annual_series(gaap, CASH_TAGS, instant=True)
    lt_debt, lt_tags = _annual_series(gaap, LONG_TERM_DEBT_TAGS, instant=True)
    cur_debt, cur_tags = _annual_series(gaap, CURRENT_DEBT_TAGS, instant=True)

    # Where operating income is untagged, rebuild EBIT from its definition:
    # pre-tax income plus interest expense. IBM and Pfizer need this.
    if not operating_income:
        pretax, pretax_tags = _annual_series(
            gaap, PRETAX_INCOME_TAGS, instant=False)
        for end in set(pretax) & set(interest):
            operating_income[end] = pretax[end] + abs(interest[end])
        if operating_income:
            notes["operating_income"] = (
                "This filer does not tag OperatingIncomeLoss. EBIT was "
                "rebuilt as pre-tax income plus interest expense, using "
                f"{', '.join(pretax_tags)}.")

    # EBITDA is not a GAAP concept, so no filer reports it as a tag. It is
    # rebuilt from its definition: operating income plus depreciation and
    # amortization. Both inputs are reported figures, so this is a disclosed
    # reconstruction rather than an estimate -- and the note below says so in
    # the output.
    ebitda: Dict[str, float] = {}
    for end in set(operating_income) & set(depreciation):
        ebitda[end] = operating_income[end] + depreciation[end]
    if ebitda:
        notes["ebitda"] = (
            "EBITDA is not a GAAP line item, so no company reports it directly. "
            "It was computed here as Operating Income plus Depreciation & "
            f"Amortization, using the reported tags OperatingIncomeLoss and "
            f"{', '.join(dep_tags)}.")

    total_assets, _ = _annual_series(gaap, TOTAL_ASSETS_TAGS, instant=True)
    current_assets, _ = _annual_series(gaap, CURRENT_ASSETS_TAGS, instant=True)
    current_liabilities, _ = _annual_series(
        gaap, CURRENT_LIABILITIES_TAGS, instant=True)
    retained, _ = _annual_series(gaap, RETAINED_EARNINGS_TAGS, instant=True)
    total_liabilities, _ = _annual_series(
        gaap, TOTAL_LIABILITIES_TAGS, instant=True)
    equity, _ = _annual_series(gaap, EQUITY_TAGS, instant=True)

    # Many filers tag assets and equity but not total liabilities. The
    # accounting identity (assets = liabilities + equity) gives it exactly,
    # so this is arithmetic on reported figures rather than an estimate.
    for end in set(total_assets) & set(equity):
        total_liabilities.setdefault(end, total_assets[end] - equity[end])

    total_debt = _sum_series(lt_debt, cur_debt)
    if total_debt:
        notes["total_debt"] = (
            "Total debt was computed by adding the reported long-term and "
            f"current borrowing tags ({', '.join(lt_tags + cur_tags)}), "
            "including finance-lease obligations where tagged. Filings report "
            "these separately; there is no single total-debt tag, and figures "
            "from data aggregators may differ because they draw the boundary "
            "elsewhere -- some include operating leases, some do not.")
    if revenue_tags:
        notes["revenue"] = (
            f"Revenue taken from the XBRL tag(s) {', '.join(revenue_tags)}.")

    # Periods present in enough of the data to be worth building a year from.
    periods = sorted(set(revenue) | set(ebitda) | set(total_debt) | set(ocf))
    if not periods:
        raise EdgarError(
            f"No annual figures could be extracted for {ticker.upper()}. The "
            "company files with the SEC, but tags its statements with concepts "
            "this tool does not recognise — filers have considerable latitude "
            "in which XBRL tags they use.\n\n"
            "Switch the data source to Yahoo Finance for this company.")
    periods = periods[-max_years:]

    scale = 1e6  # report in millions, as the rest of the project does

    def at(series: Dict[str, float], end: str,
           absolute: bool = False) -> Optional[float]:
        value = series.get(end)
        if value is None:
            return None
        value = abs(value) if absolute else value
        return value / scale

    years: List[FiscalYear] = []
    for end in periods:
        years.append(FiscalYear(
            year=int(end[:4]),
            revenue=at(revenue, end),
            ebitda=at(ebitda, end),
            # Both stored positive, meaning "money out", matching the
            # convention the rest of the project uses.
            interest_expense=at(interest, end, absolute=True),
            capex=at(capex, end, absolute=True),
            cash=at(cash, end),
            total_debt=at(total_debt, end),
            operating_cash_flow=at(ocf, end),
            total_assets=at(total_assets, end),
            current_assets=at(current_assets, end),
            current_liabilities=at(current_liabilities, end),
            retained_earnings=at(retained, end),
            total_liabilities=at(total_liabilities, end),
            shareholders_equity=at(equity, end),
            operating_income=at(operating_income, end),
        ))

    maturities = _maturity_schedule(gaap, periods[-1], scale)
    if maturities is not None:
        notes["maturities"] = (
            "The debt maturity schedule comes from the long-term debt note of "
            "the 10-K. It is reported once, as of the latest balance-sheet "
            "date, and answers the question leverage cannot: when the debt "
            "actually comes due.")

    return FinancialHistory(
        ticker=ticker.upper(),
        company_name=str(facts.get("entityName") or registered_name),
        years=years,
        currency="USD",
        units="millions",
        source="SEC EDGAR (official filings)",
        # EDGAR carries no sector classification. SIC codes exist in the
        # submissions endpoint but map poorly onto the sector names the peer
        # benchmark is keyed by, so the field is left empty rather than filled
        # with something that would silently mismatch.
        sector=None,
        industry=None,
        provenance=(
            f"Retrieved from the SEC's XBRL companyfacts API for CIK "
            f"{cik:010d}. These are figures as filed with the SEC, taken from "
            "the company's own 10-K filings. Where a period was restated in a "
            "later filing, the most recently filed value is used."),
        maturities=maturities,
        notes=notes,
    )
