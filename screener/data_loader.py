"""
Stage 1: getting the raw numbers.

Two sources are supported, behind one function: load_history().

  source="local"     Read a JSON file from data/. Works offline. This is also
                     how you enter numbers by hand from a real 10-K, which is
                     the best way to learn where these line items live.

  source="yfinance"  Pull from Yahoo Finance via the yfinance package
                     (pip install yfinance). Free, no API key.

Adding a third source later (SEC EDGAR is the natural next one) means writing
one more _load_*() function that returns a FinancialHistory. Nothing else in
the project needs to change -- that is the whole point of this boundary.

THE RULE THIS FILE ENFORCES: if a number is not in the source data, the field
stays None. We do not substitute zero, we do not interpolate from neighbouring
years, and we do not estimate. A screening tool that silently invents inputs
produces confident nonsense, which is worse than producing nothing.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .models import FinancialHistory, FiscalYear

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class DataLoadError(Exception):
    """Raised when we cannot load data at all. main.py catches this and
    prints a readable message instead of a traceback."""


# ---------------------------------------------------------------------------
# Source 1: local JSON
# ---------------------------------------------------------------------------

def _coerce_number(value: Any, field_name: str, year: Any) -> Optional[float]:
    """Turn a JSON value into a float, or None.

    Accepts: numbers, null, "" (treated as missing), and numeric strings.
    Rejects anything else loudly -- a typo in your data file should be an
    error you see, not a silent None that quietly weakens the analysis.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise DataLoadError(
            f"Field '{field_name}' for year {year} is not a number: {value!r}. "
            "Use null if the value is genuinely unavailable."
        )


def _load_local(ticker: str, path: Optional[str] = None) -> FinancialHistory:
    """Load from data/<TICKER>.json (see data/EXMPL.json for the format)."""
    if path is None:
        path = os.path.join(DATA_DIR, f"{ticker.upper()}.json")

    if not os.path.exists(path):
        available = []
        if os.path.isdir(DATA_DIR):
            available = sorted(
                f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".json")
            )
        raise DataLoadError(
            f"No local data file found at {path}.\n"
            f"Tickers available locally: {', '.join(available) or '(none)'}\n"
            "Either create that JSON file (copy data/EXMPL.json as a template) "
            "or use --source yfinance to fetch from the internet."
        )

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: Dict[str, Any] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"{path} is not valid JSON: {exc}")

    rows = raw.get("fiscal_years")
    if not isinstance(rows, list) or not rows:
        raise DataLoadError(
            f"{path} must contain a non-empty 'fiscal_years' list."
        )

    years: List[FiscalYear] = []
    for row in rows:
        if "year" not in row:
            raise DataLoadError(f"A fiscal_years entry in {path} has no 'year'.")
        y = row["year"]
        years.append(
            FiscalYear(
                year=int(y),
                revenue=_coerce_number(row.get("revenue"), "revenue", y),
                ebitda=_coerce_number(row.get("ebitda"), "ebitda", y),
                interest_expense=_coerce_number(
                    row.get("interest_expense"), "interest_expense", y),
                cash=_coerce_number(row.get("cash"), "cash", y),
                total_debt=_coerce_number(row.get("total_debt"), "total_debt", y),
                operating_cash_flow=_coerce_number(
                    row.get("operating_cash_flow"), "operating_cash_flow", y),
                capex=_coerce_number(row.get("capex"), "capex", y),
            )
        )

    return FinancialHistory(
        ticker=raw.get("ticker", ticker).upper(),
        company_name=raw.get("company_name", ticker.upper()),
        years=years,
        currency=raw.get("currency", "USD"),
        units=raw.get("units", "millions"),
        source="local JSON",
        sector=raw.get("sector") or None,
        industry=raw.get("industry") or None,
        provenance=raw.get("source_note", f"Local file: {os.path.basename(path)}"),
        notes=raw.get("notes", {}) or {},
    )


# ---------------------------------------------------------------------------
# Source 2: yfinance
# ---------------------------------------------------------------------------

# Yahoo's row labels drift between yfinance versions, so for each field we try
# several known labels in order of preference. First match wins; no match
# leaves the field None.
_YF_LABELS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "depreciation": [
        "Reconciled Depreciation",
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
        "Depreciation",
    ],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "cash": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash Financial",
    ],
    "total_debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt"],
    "current_debt": ["Current Debt", "Current Debt And Capital Lease Obligation"],
    "operating_cash_flow": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    # Extended balance-sheet set, used only by the Altman Z''-score.
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "retained_earnings": ["Retained Earnings"],
    "total_liabilities": ["Total Liabilities Net Minority Interest",
                          "Total Liabilities"],
    "shareholders_equity": ["Stockholders Equity",
                            "Total Equity Gross Minority Interest"],
}


def _pick(frame: Any, labels: List[str], column: Any) -> Optional[float]:
    """Pull one value out of a yfinance DataFrame by trying several row labels.

    Returns None if no label matches or the cell is empty. Yahoo frequently
    omits rows for some companies and years; that is a missing value, not an
    error, and it must stay None.
    """
    if frame is None or getattr(frame, "empty", True):
        return None
    for label in labels:
        if label in frame.index:
            try:
                value = frame.loc[label, column]
            except (KeyError, IndexError):
                continue
            # pandas NaN != NaN, which is how we detect an empty cell.
            if value is None or value != value:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _load_yfinance(ticker: str, max_years: int = 5) -> FinancialHistory:
    """Fetch from Yahoo Finance.

    Yahoo reports in whole currency units (e.g. 1234000000.0), so we divide by
    1e6 to keep everything in millions and consistent with the local files.
    """
    try:
        import yfinance  # noqa: F401  (imported lazily so the rest of the
        #                               project runs with no dependencies)
    except ImportError:
        raise DataLoadError(
            "The yfinance package is not installed.\n"
            "Install it with:  pip install yfinance\n"
            "Or use --source local to read from a JSON file in data/."
        )

    try:
        tk = yfinance.Ticker(ticker.upper())
        income = tk.income_stmt
        balance = tk.balance_sheet
        cashflow = tk.cashflow
        info: Dict[str, Any] = {}
        try:
            info = tk.info or {}
        except Exception:
            # .info is the flakiest part of yfinance and is only used for the
            # display name, so a failure here must not stop the analysis.
            info = {}
    except Exception as exc:
        raise DataLoadError(
            f"Could not fetch data for '{ticker}' from Yahoo Finance: {exc}\n"
            "Check the ticker spelling and your internet connection."
        )

    if income is None or getattr(income, "empty", True):
        raise DataLoadError(
            f"Yahoo Finance returned no income statement for '{ticker}'. "
            "The ticker may be wrong, delisted, or not covered."
        )

    # Columns are period-end dates, newest first. Take the most recent N.
    columns = list(income.columns)[:max_years]
    notes: Dict[str, str] = {}
    years: List[FiscalYear] = []
    scale = 1e6  # convert to millions

    for col in columns:
        def val(key: str, frame: Any) -> Optional[float]:
            raw_value = _pick(frame, _YF_LABELS[key], col)
            return None if raw_value is None else raw_value / scale

        revenue = val("revenue", income)
        ebitda = val("ebitda", income)

        # If Yahoo gives no EBITDA line, rebuild it from its definition:
        #   EBITDA = Operating Income + Depreciation & Amortization
        # This is a disclosed reconstruction, not an invention -- both inputs
        # are reported figures. The note below surfaces it in the report.
        if ebitda is None:
            op_income = val("operating_income", income)
            dep = val("depreciation", cashflow)
            if dep is None:
                dep = val("depreciation", income)
            if op_income is not None and dep is not None:
                ebitda = op_income + dep
                notes["ebitda"] = (
                    "EBITDA was not reported directly by the source; it was "
                    "computed as Operating Income + Depreciation & Amortization."
                )

        # Total Debt is usually present; if not, rebuild it from its parts.
        total_debt = val("total_debt", balance)
        if total_debt is None:
            ltd = val("long_term_debt", balance)
            cur = val("current_debt", balance)
            parts = [p for p in (ltd, cur) if p is not None]
            if parts:
                total_debt = sum(parts)
                notes["total_debt"] = (
                    "Total Debt was not reported directly; it was computed by "
                    "adding the reported long-term and current debt lines."
                )

        interest = val("interest_expense", income)
        if interest is not None:
            interest = abs(interest)  # store as positive "money paid out"

        capex = val("capex", cashflow)
        if capex is not None:
            capex = abs(capex)  # store as positive "money spent"

        # Total liabilities may be absent; the accounting identity
        # (assets = liabilities + equity) supplies it exactly, not by estimate.
        total_assets = val("total_assets", balance)
        equity = val("shareholders_equity", balance)
        total_liabilities = val("total_liabilities", balance)
        if total_liabilities is None and total_assets is not None \
                and equity is not None:
            total_liabilities = total_assets - equity

        years.append(
            FiscalYear(
                year=int(getattr(col, "year", 0)) or 0,
                revenue=revenue,
                ebitda=ebitda,
                interest_expense=interest,
                cash=val("cash", balance),
                total_debt=total_debt,
                operating_cash_flow=val("operating_cash_flow", cashflow),
                capex=capex,
                total_assets=total_assets,
                current_assets=val("current_assets", balance),
                current_liabilities=val("current_liabilities", balance),
                retained_earnings=val("retained_earnings", balance),
                total_liabilities=total_liabilities,
                shareholders_equity=equity,
                operating_income=val("operating_income", income),
            )
        )

    if not years:
        raise DataLoadError(f"No fiscal years could be parsed for '{ticker}'.")

    return FinancialHistory(
        ticker=ticker.upper(),
        company_name=info.get("longName") or info.get("shortName") or ticker.upper(),
        years=years,
        currency=info.get("financialCurrency", "USD"),
        units="millions",
        source="yfinance (Yahoo Finance)",
        sector=info.get("sector") or None,
        industry=info.get("industry") or None,
        provenance=(
            "Fetched from Yahoo Finance via the yfinance package. Yahoo is an "
            "unofficial, aggregated source: line items are occasionally missing "
            "or restated. For any conclusion that matters, verify against the "
            "company's own 10-K or 10-Q filing."
        ),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Source 3: SEC EDGAR
# ---------------------------------------------------------------------------

def _load_edgar(ticker: str, max_years: int = 5) -> FinancialHistory:
    """Official SEC filings. See screener/edgar.py for the detail.

    The import is deferred so that the rest of the project keeps working if
    that module is ever absent, and EdgarError is converted to DataLoadError
    so every caller still handles exactly one exception type.
    """
    try:
        from .edgar import EdgarError, load_edgar_history
    except ImportError as exc:
        raise DataLoadError(f"The EDGAR source is unavailable: {exc}")

    try:
        return load_edgar_history(ticker, max_years=max_years)
    except EdgarError as exc:
        raise DataLoadError(str(exc))


# ---------------------------------------------------------------------------
# The single entry point
# ---------------------------------------------------------------------------

def load_history(ticker: str,
                 source: str = "local",
                 max_years: int = 5,
                 path: Optional[str] = None) -> FinancialHistory:
    """Load a company's financial history from the chosen source.

    Raises DataLoadError with a readable message on any failure.
    """
    if not ticker or not ticker.strip():
        raise DataLoadError("No ticker given.")

    source = source.lower().strip()
    if source == "local":
        return _load_local(ticker, path=path)
    if source in ("yfinance", "yahoo"):
        return _load_yfinance(ticker, max_years=max_years)
    if source in ("edgar", "sec"):
        return _load_edgar(ticker, max_years=max_years)
    raise DataLoadError(
        f"Unknown source '{source}'. Use 'local', 'yfinance' or 'edgar'."
    )
