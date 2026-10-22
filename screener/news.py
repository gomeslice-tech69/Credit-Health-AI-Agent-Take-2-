"""
Industry watch: live restructuring activity, read from SEC filings.

WHY FILINGS RATHER THAN HEADLINES

A news feed would mean scraping somebody's website, which breaks without
warning, usually needs a paid key, and gives you a journalist's summary of an
event rather than the event. The SEC's full-text search covers every filing by
every US public company, is free, needs no key, and returns the primary
document.

That is a better fit for this project in three ways. It is the same source the
screener already reads, so the tool has one view of the world rather than two.
It returns events rather than opinion -- a Chapter 11 petition, a restructuring
support agreement, a going-concern warning. And every item links to the filing
itself, so a reader can check the claim rather than take it on trust.

The trade-off, stated plainly: this is not journalism. It will not tell you a
sector is under pressure or that a deal is rumoured. It tells you what has been
formally filed, which is narrower and more reliable.

WHAT IT WATCHES

Five categories of distress event, each a phrase that appears in filings when
something specific has happened. The phrases are deliberately literal: filings
are legal documents, and the language in them is stable in a way headlines are
not.

Requires SEC_USER_AGENT, the same contact string the EDGAR source uses.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .edgar import EdgarError, user_agent

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_nodash}/{adsh}-index.htm"


@dataclass
class Filing:
    """One restructuring-related filing."""

    date: str
    company: str
    tickers: List[str]
    cik: str
    form: str
    accession: str
    category: str

    @property
    def url(self) -> str:
        """Link to the filing index on EDGAR."""
        return FILING_URL.format(cik=self.cik.lstrip("0") or self.cik,
                                 adsh_nodash=self.accession.replace("-", ""),
                                 adsh=self.accession)

    @property
    def primary_ticker(self) -> Optional[str]:
        """The first ticker, which is the one worth screening.

        Note that a company in Chapter 11 often trades under a ticker ending
        in Q -- LESLQ rather than LESL. Both may be listed; the plain one is
        preferred because it is the one the data sources still recognise.
        """
        plain = [t for t in self.tickers if not t.endswith("Q")]
        return (plain or self.tickers or [None])[0]


@dataclass
class Category:
    """One watched event type."""

    key: str
    label: str
    phrase: str
    forms: List[str]
    explanation: str
    filings: List[Filing] = field(default_factory=list)


# The phrases are literal because filings are legal documents: the wording is
# stable in a way headlines are not. Each is tied to a specific event.
CATEGORIES: List[Category] = [
    Category(
        key="chapter11",
        label="Chapter 11 petitions",
        phrase='"chapter 11"',
        forms=["8-K"],
        explanation=(
            "A company has filed for reorganisation under Chapter 11, or has "
            "disclosed something material about an existing case. This is the "
            "end point the whole screen is trying to anticipate — which makes "
            "these the most useful filings to read against a screening "
            "score."),
    ),
    Category(
        key="rsa",
        label="Restructuring support agreements",
        phrase='"restructuring support agreement"',
        forms=["8-K"],
        explanation=(
            "A deal struck with creditors before or during a restructuring, "
            "setting out what each class receives. An RSA usually means the "
            "outcome has been negotiated rather than litigated, and it often "
            "appears days before a Chapter 11 filing."),
    ),
    Category(
        key="going_concern",
        label="Going-concern doubt",
        phrase='"substantial doubt about its ability to continue as a going concern"',
        forms=["10-K", "10-Q"],
        explanation=(
            "Auditors are required to say when they doubt a company can "
            "survive twelve months. This is the strongest formal warning in "
            "financial reporting, and it typically precedes distress by "
            "quarters rather than years."),
    ),
    Category(
        key="forbearance",
        label="Forbearance and covenant waivers",
        phrase='"forbearance agreement"',
        forms=["8-K"],
        explanation=(
            "Lenders agreeing not to enforce their rights after a breach, "
            "usually for a fixed window. A forbearance is a negotiation in "
            "progress: the company has tripped something and is buying time. "
            "This is exactly the covenant headroom the screener cannot see."),
    ),
    Category(
        key="dip",
        label="Debtor-in-possession financing",
        phrase='"debtor-in-possession"',
        forms=["8-K"],
        explanation=(
            "New money lent to a company already in bankruptcy, ranking ahead "
            "of existing debt. DIP financing is a specialism of private credit "
            "funds, and its terms say a great deal about how much value "
            "lenders think is left."),
    ),
]

_DEFAULT_WINDOW_DAYS = 180
_MAX_PER_CATEGORY = 12


class NewsUnavailable(Exception):
    """Raised when the feed cannot be fetched. The interface shows the reason
    rather than an empty list, so 'nothing found' is never confused with
    'could not look'."""


def _fetch(phrase: str, forms: List[str], days: int) -> List[Dict]:
    """Run one full-text search against EDGAR."""
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    end = _dt.date.today().isoformat()
    params = {
        "q": phrase,
        "forms": ",".join(forms),
        "dateRange": "custom",
        "startdt": start,
        "enddt": end,
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)

    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent(),
                      "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            payload = json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise NewsUnavailable(
                "The SEC rejected the request. SEC_USER_AGENT must contain a "
                "real contact email address.")
        raise NewsUnavailable(f"The SEC returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise NewsUnavailable(f"Could not reach the SEC: {exc.reason}")
    except (ValueError, KeyError):
        raise NewsUnavailable("The SEC returned an unexpected response.")

    return (payload.get("hits") or {}).get("hits") or []


# "Company Name  (TICK, TICKQ)  (CIK 0001234567)"
_NAME_RE = re.compile(r"^(?P<name>.+?)\s*(?:\((?P<tickers>[^)]*)\)\s*)?\(CIK\s*(?P<cik>\d+)\)")


def _parse_display_name(text: str) -> Dict[str, object]:
    """Pull company, tickers and CIK out of EDGAR's display string."""
    match = _NAME_RE.match(text.strip())
    if not match:
        return {"name": text.strip(), "tickers": [], "cik": ""}
    tickers = [t.strip() for t in (match.group("tickers") or "").split(",")
               if t.strip()]
    return {"name": match.group("name").strip(),
            "tickers": tickers,
            "cik": match.group("cik")}


def fetch_category(category: Category, days: int = _DEFAULT_WINDOW_DAYS,
                   limit: int = _MAX_PER_CATEGORY) -> Category:
    """Fetch one category's recent filings, newest first and de-duplicated.

    A single event often produces several near-identical hits — EDGAR indexes
    each document in a filing separately, so one 8-K can appear three times.
    De-duplicating by accession number collapses those back into one event.
    """
    hits = _fetch(category.phrase, category.forms, days)

    seen = set()
    filings: List[Filing] = []
    for hit in hits:
        source = hit.get("_source") or {}
        accession = source.get("adsh")
        if not accession or accession in seen:
            continue
        seen.add(accession)

        names = source.get("display_names") or []
        parsed = _parse_display_name(names[0] if names else "Unknown filer")
        filings.append(Filing(
            date=source.get("file_date") or "",
            company=str(parsed["name"]),
            tickers=list(parsed["tickers"]),
            cik=str(parsed["cik"]),
            form=source.get("form") or source.get("file_type") or "",
            accession=accession,
            category=category.label,
        ))

    filings.sort(key=lambda f: f.date, reverse=True)
    category.filings = filings[:limit]
    return category


def fetch_all(days: int = _DEFAULT_WINDOW_DAYS,
              limit: int = _MAX_PER_CATEGORY) -> List[Category]:
    """Fetch every category.

    One category failing does not fail the rest: a partial feed is more useful
    than none, and the interface reports which came back empty.
    """
    results: List[Category] = []
    for template in CATEGORIES:
        category = Category(key=template.key, label=template.label,
                            phrase=template.phrase, forms=list(template.forms),
                            explanation=template.explanation)
        try:
            results.append(fetch_category(category, days=days, limit=limit))
        except NewsUnavailable:
            results.append(category)  # left with no filings
    return results


def is_configured() -> bool:
    """True when the SEC contact string is set, which this shares with EDGAR."""
    try:
        user_agent()
        return True
    except EdgarError:
        return False
