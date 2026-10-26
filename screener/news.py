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


# ---------------------------------------------------------------------------
# Press coverage
#
# The SEC feed above reports what has been FILED. This one reports what is
# being WRITTEN, which is a different and complementary thing: journalists
# cover rumour, negotiation and sector pressure weeks before any of it reaches
# a filing, and they cover private credit, which barely files at all.
#
# A SUBSCRIPTION IS NOT API ACCESS. A personal WSJ or NYT subscription lets a
# person read articles in their browser; it grants an application nothing.
# What these publishers do offer is public RSS: headlines, summaries and
# links, free and without a key. The reader clicks through and their own
# subscription handles the paywall. Nothing here circumvents one.
# ---------------------------------------------------------------------------

import xml.etree.ElementTree as _ET
from email.utils import parsedate_to_datetime as _parsedate

# Public RSS endpoints. Each publisher offers these deliberately -- they are
# how syndication has always worked -- so this is not scraping.
FEEDS = [
    # Deal and credit coverage first -- these carry the highest density of
    # relevant stories. The general business feeds are included because
    # restructuring news often breaks there before it reaches a specialist
    # column.
    ("NYT DealBook", "https://rss.nytimes.com/services/xml/rss/nyt/DealBook.xml"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("WSJ Business", "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("FT Companies", "https://www.ft.com/companies?format=rss"),
    ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                     "?partnerId=wrss01&id=10000664"),
    ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                     "?partnerId=wrss01&id=20910258"),
    ("NYT Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("NYT Economy", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ("SEC press", "https://www.sec.gov/news/pressreleases.rss"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
]

# Generic business news is noise for this project, so articles are filtered.
#
# MATCHING IS ON WORD BOUNDARIES, NOT SUBSTRINGS. Plain substring matching
# looked fine and was quietly wrong: "lbo" matched "DeaLBOok", "clo" matched
# "neoCLOud", and a personal-finance column about a mortgage matched "interest
# rate". Short acronyms are exactly the terms that collide with ordinary words.
#
# Two tiers. A STRONG term is unambiguous enough to qualify an article on its
# own. A WEAK term is real vocabulary but too common to stand alone -- it
# qualifies only alongside another weak term, which keeps "debt" from dragging
# in every retirement column.
STRONG_TERMS = [
    "restructuring", "restructure", "bankruptcy", "bankrupt", "chapter 11",
    "insolvency", "insolvent", "liquidation", "private credit",
    "direct lending", "distressed", "bondholder", "creditors", "covenant",
    "forbearance", "high-yield", "junk bond", "leveraged loan",
    "leveraged buyout", "going concern", "debt restructuring",
    "maturity wall", "credit market", "debt load", "default",
    "collateralized loan", "dip financing", "chapter 7",
    # Market-level credit language. A headline about the bond market or
    # spreads is about credit conditions, which is the context the screener
    # operates in.
    "bond market", "debt market", "credit spread", "credit spreads",
    "bond risk", "debt downgrade", "credit rating", "yield spread",
    "sovereign debt", "borrowing costs", "credit conditions",
    "debt ceiling", "debt crisis",
]
WEAK_TERMS = [
    "debt", "credit", "lender", "lenders", "loan", "loans", "leverage",
    "refinance", "refinancing", "downgrade", "bond", "bonds", "yield",
    "yields", "buyout", "creditor", "spread", "spreads", "sovereign",
    "issuance", "borrowing", "maturity", "notes", "treasury", "market",
]

# Personal-finance advice columns use the same vocabulary as credit reporting
# and are never relevant here. These phrases are a reliable tell.
EXCLUDE_PATTERNS = [
    # First-person advice columns. These use identical credit vocabulary to
    # real reporting -- "debt", "loan", "credit card" -- and are never
    # relevant. The tell is always a personal narrator.
    r"\bmy (husband|wife|son|daughter|mother|father|parents|in-law|sister|brother)",
    r"\bi(?:'m| am) \d+\b", r"\bi(?:'m| am) a\b",
    r"\bi want to\b", r"\bi have \$", r"\bwe have a \$",
    r"\bshould i\b", r"\bcan i (afford|retire|claim)\b",
    r"\bhow (much|do) (should|i)\b",
    r"\bmy \$[\d,]+\b", r"\bmy (savings|pension|401|ira|mortgage|salary)\b",
    r"\bcredit[- ]card debt\b", r"\bcredit score\b",
    r"\bretire(ment)? (plan|account|savings)\b",
    r"\bsign up for\b", r"\bnewsletter\b",
    r"\bdear (quentin|penny|moneyist)\b", r"\bmoneyist\b",
    r"\bpersonal finance\b", r"\bmy financial adviser\b",
]

_STRONG_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(t) for t in STRONG_TERMS) + r")(?![a-z])",
    re.I)
_WEAK_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(t) for t in WEAK_TERMS) + r")(?![a-z])",
    re.I)
_EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS), re.I)

_RSS_UA = ("Mozilla/5.0 (compatible; CreditHealthAgent/1.0; educational "
           "project; +https://github.com/gomeslice-tech69)")


@dataclass
class Article:
    """One syndicated headline."""

    title: str
    link: str
    source: str
    published: Optional[str]
    summary: str
    matched: List[str] = field(default_factory=list)


def _clean(text: Optional[str]) -> str:
    """Strip tags and collapse whitespace out of an RSS description."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _parse_feed(raw: bytes, source: str) -> List[Article]:
    """Parse an RSS document into articles.

    A malformed feed returns nothing rather than raising: one publisher
    changing their XML must not take down the whole page.
    """
    try:
        root = _ET.fromstring(raw)
    except _ET.ParseError:
        return []

    articles: List[Article] = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue

        raw_date = item.findtext("pubDate") or item.findtext("published")
        published = None
        if raw_date:
            try:
                published = _parsedate(raw_date).date().isoformat()
            except (TypeError, ValueError):
                published = None

        articles.append(Article(
            title=title, link=link, source=source, published=published,
            summary=_clean(item.findtext("description"))[:320]))
    return articles


def _relevant(article: Article) -> bool:
    """Keep an article only if it genuinely concerns credit or distress.

    One strong term qualifies an article. Two weak terms also qualify, which
    catches real reporting that happens not to use a headline keyword. A
    personal-finance advice column is rejected outright however it scores --
    those use identical vocabulary and are never relevant here.

    The matched terms are recorded so the interface can show why an article
    was kept, rather than asking the reader to trust the filter.
    """
    haystack = article.title + " " + article.summary

    if _EXCLUDE_RE.search(haystack):
        article.matched = []
        return False

    strong = {m.group(0).lower() for m in _STRONG_RE.finditer(haystack)}
    weak = {m.group(0).lower() for m in _WEAK_RE.finditer(haystack)}

    if strong:
        article.matched = sorted(strong)
        return True
    if len(weak) >= 2:
        article.matched = sorted(weak)
        return True

    article.matched = []
    return False


def fetch_press(limit: int = 30, filtered: bool = True) -> List[Article]:
    """Pull every feed and return the credit-relevant articles, newest first.

    One feed failing does not fail the rest. Publishers change endpoints and
    rate-limit without warning, so a partial page beats an error page.
    """
    collected: List[Article] = []
    seen_links = set()

    for source, url in FEEDS:
        request = urllib.request.Request(
            url, headers={"User-Agent": _RSS_UA,
                          "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except Exception:
            continue

        for article in _parse_feed(raw, source):
            if article.link in seen_links:
                continue
            seen_links.add(article.link)
            if filtered and not _relevant(article):
                continue
            if not filtered:
                _relevant(article)
            collected.append(article)

    collected.sort(key=lambda a: a.published or "", reverse=True)
    return collected[:limit]


def feed_sources() -> List[str]:
    """The publishers consulted, for display."""
    return sorted({name for name, _ in FEEDS})
