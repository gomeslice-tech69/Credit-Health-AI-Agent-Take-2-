"""
Industry briefing: what the filings and headlines add up to.

WHY THIS IS COMPUTED RATHER THAN WRITTEN

The obvious way to summarise an industry is to hand a pile of headlines to a
language model and ask for a paragraph. That produces something readable and
unverifiable, different on every run, and impossible to check.

This does the opposite. It counts: how many distress filings landed this month
against last, which industries they came from, which specific 8-K items were
triggered, what the press is actually writing about. The prose is assembled
from those counts, so every sentence traces to a number a reader can verify.

That makes the briefing boring in the way an instrument should be boring. It
will not tell you a sector "feels" stressed. It will tell you that eleven
pharmaceutical companies filed bankruptcy 8-Ks in the last sixty days against
four in the sixty before, which is a claim with a denominator.

THE 8-K ITEM NUMBERS MATTER

Companies file 8-Ks under numbered items, and the numbering is prescribed by
the SEC rather than chosen. Item 1.03 is "Bankruptcy or Receivership" — a
filing carrying it has entered an insolvency process, full stop. That is a
harder signal than any phrase search, because it cannot be triggered by a
company merely discussing bankruptcy in passing.
"""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .news import CATEGORIES, Category, NewsUnavailable, _fetch, fetch_press

# 8-K items that mean something specific about credit distress. The SEC
# prescribes this numbering, so these are precise rather than interpretive.
DISTRESS_ITEMS = {
    "1.03": "Bankruptcy or receivership",
    "2.04": "Debt acceleration or increased obligation",
    "3.01": "Delisting notice or listing-rule failure",
    "4.02": "Previously issued statements no longer reliable",
}

# SIC major groups, by the first two digits. Enough to say which part of the
# economy is filing without pretending to more precision than the code carries.
SIC_GROUPS: List[Tuple[Tuple[int, int], str]] = [
    ((1, 9), "Agriculture"), ((10, 14), "Mining and energy"),
    ((15, 17), "Construction"), ((20, 21), "Food and tobacco"),
    ((22, 23), "Textiles and apparel"), ((24, 27), "Wood, paper and printing"),
    ((28, 28), "Pharmaceuticals and chemicals"),
    ((29, 30), "Petroleum, rubber and plastics"),
    ((31, 34), "Leather, stone and metals"),
    ((35, 35), "Industrial machinery"), ((36, 36), "Electronics"),
    ((37, 37), "Transport equipment"), ((38, 39), "Instruments and other"),
    ((40, 47), "Transportation"), ((48, 48), "Communications"),
    ((49, 49), "Utilities"), ((50, 51), "Wholesale"),
    ((52, 59), "Retail"), ((60, 64), "Banking and insurance"),
    ((65, 67), "Real estate and investment"),
    ((70, 79), "Hotels, services and entertainment"),
    ((80, 87), "Health, legal and professional services"),
    ((88, 99), "Other"),
]


def sic_to_group(sic: str) -> str:
    """Map a four-digit SIC code to a readable industry group."""
    try:
        major = int(str(sic)[:2])
    except (TypeError, ValueError):
        return "Unclassified"
    for (low, high), label in SIC_GROUPS:
        if low <= major <= high:
            return label
    return "Unclassified"


@dataclass
class Window:
    """Counts over one time window."""

    days: int
    total: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_industry: Counter = field(default_factory=Counter)
    by_item: Counter = field(default_factory=Counter)
    companies: set = field(default_factory=set)


@dataclass
class Briefing:
    """Everything the briefing page needs, all of it counted."""

    generated: str
    recent: Window
    prior: Window
    themes: List[Tuple[str, int]] = field(default_factory=list)
    headline_count: int = 0
    repeat_filers: List[Tuple[str, int]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def change_pct(self) -> Optional[float]:
        """Change in distress filings, recent window against the prior one."""
        if not self.prior.total:
            return None
        return (self.recent.total - self.prior.total) / self.prior.total


def _count(days_back_start: int, days_back_end: int,
           window_days: int) -> Window:
    """Count filings whose date falls in a window ending days_back_end ago."""
    today = _dt.date.today()
    hi = today - _dt.timedelta(days=days_back_end)
    lo = today - _dt.timedelta(days=days_back_start)
    window = Window(days=window_days)

    for template in CATEGORIES:
        try:
            hits = _fetch(template.phrase, template.forms, days_back_start)
        except NewsUnavailable:
            continue

        seen = set()
        for hit in hits:
            source = hit.get("_source") or {}
            accession = source.get("adsh")
            raw_date = source.get("file_date") or ""
            if not accession or accession in seen:
                continue
            try:
                filed = _dt.date.fromisoformat(raw_date)
            except ValueError:
                continue
            if not (lo <= filed <= hi):
                continue
            seen.add(accession)

            window.total += 1
            window.by_category[template.label] = (
                window.by_category.get(template.label, 0) + 1)
            for sic in (source.get("sics") or []):
                window.by_industry[sic_to_group(sic)] += 1
            for item in (source.get("items") or []):
                if item in DISTRESS_ITEMS:
                    window.by_item[item] += 1
            names = source.get("display_names") or []
            if names:
                window.companies.add(names[0].split("  (")[0].strip())

    return window


def build(window_days: int = 60) -> Briefing:
    """Compute the briefing: two windows of filings plus press themes."""
    recent = _count(window_days, 0, window_days)
    prior = _count(window_days * 2, window_days, window_days)

    themes: List[Tuple[str, int]] = []
    headline_count = 0
    errors: List[str] = []
    try:
        articles = fetch_press(limit=120, filtered=True)
        headline_count = len(articles)
        counter: Counter = Counter()
        for article in articles:
            for term in article.matched:
                counter[term] += 1
        themes = counter.most_common(8)
    except Exception as exc:
        errors.append(f"Press feeds unavailable: {exc}")

    # A company filing repeatedly in one window is usually mid-process rather
    # than newly distressed, which is worth separating out.
    repeats = Counter()
    for name in recent.companies:
        repeats[name] += 1

    return Briefing(
        generated=_dt.date.today().isoformat(),
        recent=recent, prior=prior, themes=themes,
        headline_count=headline_count,
        repeat_filers=[], errors=errors)


def summarise(briefing: Briefing) -> List[str]:
    """Assemble the briefing prose from the counts.

    Every sentence below is derived from a number the page also displays, so a
    reader can check any claim against the table beside it.
    """
    lines: List[str] = []
    recent, prior = briefing.recent, briefing.prior

    if recent.total == 0:
        return ["No distress filings were found in this window. That is more "
                "likely to mean the SEC search is unavailable than that "
                "nothing happened — check the filings tab."]

    change = briefing.change_pct
    if change is None:
        lines.append(
            f"**{recent.total} distress-related filings** landed in the last "
            f"{recent.days} days across {len(recent.by_category)} event types.")
    else:
        direction = ("up" if change > 0.05 else
                     "down" if change < -0.05 else "roughly level")
        magnitude = (f" ({abs(change):.0%} {'more' if change > 0 else 'fewer'})"
                     if abs(change) > 0.05 else "")
        lines.append(
            f"**{recent.total} distress-related filings** landed in the last "
            f"{recent.days} days, {direction} against {prior.total} in the "
            f"{prior.days} days before{magnitude}.")

    if recent.by_category:
        top = sorted(recent.by_category.items(), key=lambda kv: -kv[1])
        biggest, count = top[0]
        lines.append(
            f"The largest single category is **{biggest.lower()}** at "
            f"{count} filings.")

    bankruptcies = recent.by_item.get("1.03", 0)
    if bankruptcies:
        lines.append(
            f"**{bankruptcies} companies filed an 8-K under Item 1.03** — the "
            "SEC's prescribed item for bankruptcy or receivership. That is a "
            "harder number than a phrase search: a company cannot trigger it "
            "by merely discussing bankruptcy.")

    accelerations = recent.by_item.get("2.04", 0)
    if accelerations:
        lines.append(
            f"{accelerations} filed under Item 2.04, covering debt "
            "acceleration — typically what happens after a covenant breach, "
            "and the earliest formal sign that lenders have moved.")

    if recent.by_industry:
        top_sectors = recent.by_industry.most_common(3)
        named = ", ".join(f"**{s.lower()}** ({n})" for s, n in top_sectors)
        lines.append(f"By industry, the filings cluster in {named}.")

    if briefing.themes:
        terms = ", ".join(f"{t}" for t, _ in briefing.themes[:5])
        lines.append(
            f"Across {briefing.headline_count} credit-related headlines, the "
            f"recurring terms are {terms}.")

    lines.append(
        "These are counts of formal filings, not a judgement about the "
        "market. A rise can reflect genuine deterioration or simply the "
        "reporting calendar — several industries cluster their fiscal "
        "year-ends, and filings follow.")
    return lines
