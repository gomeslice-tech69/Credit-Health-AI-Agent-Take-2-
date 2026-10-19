"""
PLACEHOLDER for the Big Data phase. Nothing here is called by main.py yet.

The goal, eventually:

    "Company A has Net Debt/EBITDA of 4.5x compared with an industry
     median of 2.8x, placing it in the 85th percentile of its sector."

WHY THIS MATTERS, AND WHY IT IS THE RIGHT NEXT STEP

Every threshold in rating.py is a general convention. 5x leverage is routine
for a regulated utility with contracted cash flows and alarming for a cyclical
manufacturer. An absolute threshold cannot know the difference; an industry
median can. Comparing a company against its own sector is the single biggest
accuracy improvement available to this tool.

It is also the natural place for a Big Data component, because it is the first
part of the project where you genuinely need scale. One company needs seven
numbers. A credible industry median needs 20-plus companies per sector, which
means hundreds of companies, which means thinking about batching, caching,
rate limits and storage -- real data engineering, with a real reason for it.

HOW TO BUILD IT, in the order I would do it:

  1. Pick ~30 tickers across 3-4 industries, hand-written in a JSON file.
  2. Loop over them with the existing load_history(), save each result to
     data/cache/<TICKER>.json. Cache aggressively: a 10-K does not change,
     so there is no reason to re-fetch it, and Yahoo will rate-limit you.
  3. Compute metrics for each with the existing compute_all_metrics(). None of
     stages 1 and 2 need any changes -- that is the payoff of keeping them pure.
  4. Group by industry and take the median of each metric.
  5. Add a section 2b to the report showing company vs median vs percentile.

At step 2 you will want to move to SEC EDGAR's companyfacts API rather than
yfinance: it is official, it has no undocumented rate limit (just a requested
10 requests/second and a User-Agent header), and its XBRL tags are standardised
across filers, which matters enormously once you are comparing companies.

TWO STATISTICAL POINTS worth getting right, because they are easy to get wrong
and a professor may well ask:

  MEDIAN, NOT MEAN. Credit metrics have brutal outliers -- one company with
  near-zero EBITDA produces a 400x leverage ratio that would wreck a mean.
  The median ignores it. Always use the median for ratio benchmarks.

  DROP THE UNCOMPUTABLE, DO NOT ZERO THEM. A company whose leverage is None
  because EBITDA is negative must be excluded from the median, not counted as
  zero. But record how many you dropped and report it, because a sector where
  half the companies have negative EBITDA is itself the finding.

The two functions below are small, real, and tested. They are the pieces you
will need. Nothing else here is built yet.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence


def median(values: Sequence[Optional[float]]) -> Optional[float]:
    """Median of the values that exist, ignoring None. None if none exist.

    We write this out rather than using statistics.median so the None-handling
    is explicit and visible -- the whole point is that unavailable values are
    dropped, never treated as zero.
    """
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2 == 1:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def compare_to_peers(company_value: Optional[float],
                     peer_values: Sequence[Optional[float]],
                     metric_name: str = "Net Debt/EBITDA",
                     higher_is_worse: bool = True) -> Dict[str, object]:
    """Compare one company's metric against a set of peers.

    Returns a dict with the median, the company's percentile among peers, the
    number of peers actually used, and a plain-language sentence.

    `higher_is_worse` is True for leverage (more is worse) and False for
    interest coverage (more is better). Getting this backwards silently
    inverts the conclusion, which is why it is an explicit argument.
    """
    usable: List[float] = [v for v in peer_values if v is not None]
    dropped = len(peer_values) - len(usable)

    result: Dict[str, object] = {
        "metric": metric_name,
        "company_value": company_value,
        "peer_median": median(usable),
        "peers_used": len(usable),
        "peers_dropped": dropped,
        "percentile": None,
        "sentence": "",
    }

    if company_value is None:
        result["sentence"] = (
            f"{metric_name} is not available for this company, so no peer "
            "comparison is possible.")
        return result
    if not usable:
        result["sentence"] = (
            f"No peer had a computable {metric_name}, so no median could be "
            "formed.")
        return result

    below = sum(1 for v in usable if v < company_value)
    percentile = 100.0 * below / len(usable)
    result["percentile"] = percentile

    peer_median = result["peer_median"]
    assert isinstance(peer_median, float)
    gap = company_value - peer_median
    worse = (gap > 0) if higher_is_worse else (gap < 0)
    direction = "above" if gap > 0 else "below"

    result["sentence"] = (
        f"{metric_name} of {company_value:.2f} compares with a peer median of "
        f"{peer_median:.2f} ({abs(gap):.2f} {direction} the median), placing "
        f"the company in the {percentile:.0f}th percentile of "
        f"{len(usable)} peers. This is "
        f"{'worse' if worse else 'better'} than the typical peer."
    )
    if dropped:
        result["sentence"] += (
            f" Note: {dropped} peer(s) were excluded because the metric could "
            "not be computed for them.")
    return result
