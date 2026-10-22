"""
Tests for the calculation layer.

Run from the project root with:   python3 -m unittest discover -s tests -v

These tests exist for a specific reason worth stating: the whole design of this
project rests on Python doing the arithmetic and the AI only describing it. That
claim is only worth anything if the arithmetic is actually verified. These tests
are the verification.

Note how much of the file is about MISSING and WEIRD data rather than ordinary
cases. That is deliberate. Real financial data is full of gaps, negative
earnings and zero denominators, and the dangerous failure mode is not a crash
but a plausible-looking wrong number.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SEC_USER_AGENT", "test-suite test@example.com")

from screener import altman                                        # noqa: E402
from screener.altman import (compute_z_score, components,          # noqa: E402
                             is_meaningful_for)
from screener import edgar                                         # noqa: E402
from screener import metrics as M                                   # noqa: E402
from screener.models import FinancialHistory, FiscalYear            # noqa: E402
from screener.narrative import (restructuring_watch,                # noqa: E402
                                structural_caveats)
from screener.peers import (PeerCacheUnavailable,                   # noqa: E402
                            compare_to_peers, compare_to_sector,
                            load_peer_cache, median)
from screener.rating import (ELEVATED, LOW, MODERATE,              # noqa: E402
                             rate_stress)
from screener.scenario import run_ebitda_downside                   # noqa: E402
from screener.signals import evaluate_signals                       # noqa: E402


class TestSafeDivide(unittest.TestCase):
    def test_normal_division(self):
        self.assertAlmostEqual(M.safe_divide(1000, 250), 4.0)

    def test_missing_inputs_give_none(self):
        self.assertIsNone(M.safe_divide(None, 250))
        self.assertIsNone(M.safe_divide(1000, None))

    def test_zero_denominator_gives_none(self):
        self.assertIsNone(M.safe_divide(1000, 0))

    def test_negative_denominator_gives_none(self):
        """The key design decision: Debt/EBITDA with negative EBITDA must not
        return a flattering negative multiple."""
        self.assertIsNone(M.safe_divide(1000, -200))

    def test_negative_denominator_has_a_reason(self):
        reason = M.negative_denominator_reason(-200)
        self.assertIn("negative", reason)


class TestMetricFormulas(unittest.TestCase):
    def test_debt_to_ebitda(self):
        self.assertAlmostEqual(M.debt_to_ebitda(1950, 300), 6.5)

    def test_net_debt_subtracts_cash(self):
        self.assertAlmostEqual(M.net_debt(1950, 185), 1765)

    def test_net_debt_can_be_negative_when_cash_exceeds_debt(self):
        """A net cash position is good news and must survive as a number."""
        self.assertAlmostEqual(M.net_debt(300, 800), -500)

    def test_net_debt_to_ebitda_is_lower_than_gross(self):
        gross = M.debt_to_ebitda(1950, 300)
        net = M.net_debt_to_ebitda(1950, 185, 300)
        self.assertLess(net, gross)
        self.assertAlmostEqual(net, 1765 / 300)

    def test_interest_coverage(self):
        self.assertAlmostEqual(M.interest_coverage(300, 135), 300 / 135)

    def test_free_cash_flow_can_be_negative(self):
        """Unlike the ratios, a negative FCF is meaningful and must be kept."""
        self.assertAlmostEqual(M.free_cash_flow(150, 225), -75)

    def test_ebitda_margin_is_a_decimal(self):
        self.assertAlmostEqual(M.ebitda_margin(300, 3850), 300 / 3850)

    def test_revenue_growth_decline(self):
        self.assertAlmostEqual(M.revenue_growth(3850, 3990), 3850 / 3990 - 1)

    def test_revenue_growth_first_year_is_none(self):
        """No prior year means no growth rate. Correct, not a bug."""
        self.assertIsNone(M.revenue_growth(3850, None))


class TestMissingDataNeverBecomesZero(unittest.TestCase):
    """The central safety property of the whole project."""

    def test_year_with_no_data_produces_all_none(self):
        m = M.compute_year_metrics(FiscalYear(2025))
        for name in ("debt_to_ebitda", "net_debt_to_ebitda",
                     "interest_coverage", "free_cash_flow", "ebitda_margin"):
            self.assertIsNone(getattr(m, name), f"{name} should be None")
            self.assertIn(name, m.reasons, f"{name} should carry a reason")

    def test_partial_data_computes_what_it_can(self):
        """Missing cash must not stop Debt/EBITDA from being computed."""
        m = M.compute_year_metrics(
            FiscalYear(2025, ebitda=300, total_debt=1950, cash=None))
        self.assertAlmostEqual(m.debt_to_ebitda, 6.5)
        self.assertIsNone(m.net_debt_to_ebitda)

    def test_negative_ebitda_blanks_ratios_with_an_explanation(self):
        m = M.compute_year_metrics(
            FiscalYear(2025, ebitda=-100, total_debt=1000, cash=50,
                       interest_expense=60))
        self.assertIsNone(m.debt_to_ebitda)
        self.assertIn("negative", m.reasons["debt_to_ebitda"])


class TestScenario(unittest.TestCase):
    def setUp(self):
        self.fy = FiscalYear(2025, revenue=3850, ebitda=300,
                             interest_expense=135, cash=185, total_debt=1950,
                             operating_cash_flow=150, capex=225)

    def test_twenty_percent_cut_raises_leverage_by_twentyfive_percent(self):
        """The asymmetry that makes leverage dangerous: 1/0.8 - 1 = 25%."""
        r = run_ebitda_downside(self.fy, haircut=0.20)
        self.assertAlmostEqual(
            r.stressed.net_debt_to_ebitda / r.base.net_debt_to_ebitda, 1.25)

    def test_coverage_falls_by_the_same_proportion(self):
        r = run_ebitda_downside(self.fy, haircut=0.20)
        self.assertAlmostEqual(
            r.stressed.interest_coverage / r.base.interest_coverage, 0.80)

    def test_debt_cash_and_interest_are_held_constant(self):
        r = run_ebitda_downside(self.fy, haircut=0.20)
        self.assertAlmostEqual(r.base.net_debt, r.stressed.net_debt)

    def test_zero_haircut_changes_nothing(self):
        r = run_ebitda_downside(self.fy, haircut=0.0)
        self.assertAlmostEqual(r.base.net_debt_to_ebitda,
                               r.stressed.net_debt_to_ebitda)

    def test_invalid_haircut_rejected(self):
        with self.assertRaises(ValueError):
            run_ebitda_downside(self.fy, haircut=1.5)

    def test_missing_ebitda_does_not_crash(self):
        r = run_ebitda_downside(FiscalYear(2025, total_debt=1000, cash=100))
        self.assertIsNone(r.stressed_ebitda)


def _history_from(rows, ticker="TEST"):
    """Alias used by the newer test classes."""
    return _history(rows, ticker)


def _history(rows, ticker="TEST"):
    """Build a FinancialHistory from (year, rev, ebitda, cash, debt, int,
    ocf, capex) tuples."""
    years = [FiscalYear(year=r[0], revenue=r[1], ebitda=r[2], cash=r[3],
                        total_debt=r[4], interest_expense=r[5],
                        operating_cash_flow=r[6], capex=r[7]) for r in rows]
    return FinancialHistory(ticker=ticker, company_name=ticker, years=years)


DETERIORATING = [
    (2023, 4180, 430, 300, 1680, 88, 290, 250),
    (2024, 3990, 360, 240, 1800, 110, 215, 240),
    (2025, 3850, 300, 185, 1950, 135, 150, 225),
]
IMPROVING = [
    (2023, 3150, 567, 580, 850, 35, 470, 180),
    (2024, 3340, 618, 700, 820, 33, 510, 190),
    (2025, 3520, 668, 795, 800, 32, 555, 200),
]


class TestSignals(unittest.TestCase):
    def test_deteriorating_company_fires_every_signal(self):
        h = _history(DETERIORATING)
        signals = evaluate_signals(h, M.compute_all_metrics(h))
        self.assertTrue(all(s.status == "fired" for s in signals),
                        [(s.name, s.status) for s in signals])

    def test_improving_company_fires_no_signals(self):
        h = _history(IMPROVING)
        signals = evaluate_signals(h, M.compute_all_metrics(h))
        self.assertEqual([s.name for s in signals if s.fired], [])

    def test_single_year_cannot_produce_trend_signals(self):
        h = _history(DETERIORATING[-1:])
        signals = evaluate_signals(h, M.compute_all_metrics(h))
        self.assertEqual(signals[0].status, "unknown")

    def test_missing_data_gives_unknown_not_clear(self):
        """An unchecked signal must never be reported as 'no problem'."""
        rows = [(2024, 3990, None, 240, 1800, 110, 215, 240),
                (2025, 3850, None, 185, 1950, 135, 150, 225)]
        h = _history(rows)
        signals = evaluate_signals(h, M.compute_all_metrics(h))
        ebitda_signal = next(s for s in signals if s.name == "EBITDA falling")
        self.assertEqual(ebitda_signal.status, "unknown")


class TestRating(unittest.TestCase):
    def _rate(self, rows):
        h = _history(rows)
        metrics = M.compute_all_metrics(h)
        return rate_stress(metrics,
                           [(fy.year, fy.ebitda) for fy in h.sorted_years()])

    def test_deteriorating_company_rates_elevated(self):
        self.assertEqual(self._rate(DETERIORATING).rating, ELEVATED)

    def test_healthy_company_rates_low(self):
        r = self._rate(IMPROVING)
        self.assertEqual(r.rating, LOW)
        self.assertEqual(r.score, 0)

    def test_all_five_factors_assessed_with_full_data(self):
        self.assertEqual(self._rate(DETERIORATING).assessed_count, 5)

    def test_score_never_exceeds_max(self):
        r = self._rate(DETERIORATING)
        self.assertLessEqual(r.score, r.max_score)

    def test_missing_data_shrinks_the_max_not_the_score(self):
        """Unassessable factors leave the denominator, so a company with
        patchy disclosure is not flattered into a Low rating."""
        rows = [(2024, 3990, 360, None, None, 110, 215, 240),
                (2025, 3850, 300, None, None, 135, 150, 225)]
        r = self._rate(rows)
        self.assertLess(r.max_score, 13)
        self.assertLess(r.assessed_count, 5)
        self.assertIn("LOW CONFIDENCE", r.confidence_note)

    def test_negative_ebitda_is_maximum_stress_not_unassessed(self):
        """The worst case must not slip through as 'cannot assess'."""
        rows = [(2024, 3990, 50, 240, 1800, 110, 215, 240),
                (2025, 3850, -120, 185, 1950, 135, 150, 225)]
        r = self._rate(rows)
        self.assertEqual(r.rating, ELEVATED)
        leverage = next(f for f in r.factors if f.name == "Leverage level")
        self.assertEqual(leverage.points, 3)

    def test_net_cash_company_scores_zero_on_leverage(self):
        rows = [(2024, 1000, 200, 900, 300, 5, 180, 50),
                (2025, 1100, 220, 950, 300, 5, 190, 55)]
        leverage = next(f for f in self._rate(rows).factors
                        if f.name == "Leverage level")
        self.assertEqual(leverage.points, 0)
        self.assertIn("net cash", leverage.observation)


class TestPeersHelpers(unittest.TestCase):
    def test_median_odd_and_even(self):
        self.assertAlmostEqual(median([1.0, 5.0, 3.0]), 3.0)
        self.assertAlmostEqual(median([1.0, 3.0, 5.0, 7.0]), 4.0)

    def test_median_ignores_none_rather_than_zeroing_it(self):
        """If None became 0.0 the median here would be 1.0, not 3.0."""
        self.assertAlmostEqual(median([None, 1.0, 3.0, 5.0, None]), 3.0)

    def test_median_of_nothing_is_none(self):
        self.assertIsNone(median([None, None]))

    def test_comparison_reports_percentile_and_drops(self):
        result = compare_to_peers(4.5, [1.0, 2.0, 2.8, 3.5, None],
                                  "Net Debt/EBITDA")
        self.assertAlmostEqual(result["peer_median"], 2.4)
        self.assertAlmostEqual(result["percentile"], 100.0)
        self.assertEqual(result["peers_dropped"], 1)
        self.assertIn("worse", result["sentence"])

    def test_higher_is_better_metric_inverts_the_verdict(self):
        """Coverage of 10x against a median of 4x is BETTER, not worse."""
        result = compare_to_peers(10.0, [2.0, 4.0, 6.0], "Interest coverage",
                                  higher_is_worse=False)
        self.assertIn("better", result["sentence"])


if __name__ == "__main__":
    unittest.main()


class TestScenarioGuardsAgainstNegativeEbitda(unittest.TestCase):
    """A 20% cut applied to negative EBITDA would make it LESS negative and so
    would read as an improvement. The scenario must refuse to run instead."""

    def test_negative_ebitda_scenario_is_not_run(self):
        fy = FiscalYear(2025, revenue=900, ebitda=-120, interest_expense=55,
                        cash=100, total_debt=1000)
        r = run_ebitda_downside(fy, haircut=0.20)
        self.assertFalse(r.meaningful)
        self.assertIsNone(r.stressed_ebitda)
        self.assertIn("liquidity", r.note)

    def test_negative_ebitda_never_shows_an_improvement(self):
        fy = FiscalYear(2025, revenue=900, ebitda=-120, interest_expense=55,
                        cash=100, total_debt=1000)
        r = run_ebitda_downside(fy, haircut=0.20)
        self.assertAlmostEqual(r.base.interest_coverage,
                               r.stressed.interest_coverage)

    def test_zero_ebitda_scenario_is_not_run(self):
        r = run_ebitda_downside(FiscalYear(2025, ebitda=0, total_debt=500))
        self.assertFalse(r.meaningful)

    def test_positive_ebitda_scenario_still_runs(self):
        fy = FiscalYear(2025, ebitda=300, total_debt=1950, cash=185,
                        interest_expense=135)
        r = run_ebitda_downside(fy, haircut=0.20)
        self.assertTrue(r.meaningful)
        self.assertAlmostEqual(r.stressed_ebitda, 240)


class TestStructuralCaveats(unittest.TestCase):
    """A correctly-calculated number can still be the wrong lens.

    Ford screens at ~39x leverage because Ford Credit's debt funds a loan book
    whose income is not in EBITDA. The arithmetic is right; the interpretation
    would be badly wrong without a warning.
    """

    def _caveats(self, rows):
        h = _history(rows)
        return structural_caveats(h, M.compute_all_metrics(h))

    def test_captive_finance_leverage_is_flagged(self):
        # Huge debt, thin EBITDA: the finance-arm signature.
        rows = [(2024, 185000, 4800, 40000, 160000, 1300, 15000, 8000),
                (2025, 190000, 3600, 38000, 165000, 1330, 20000, 7500)]
        caveats = self._caveats(rows)
        self.assertTrue(caveats, "implausible leverage should be flagged")
        titles = " ".join(t for t, _ in caveats)
        self.assertIn("implausibly high", titles)
        body = " ".join(b for _, b in caveats)
        self.assertIn("captive finance", body)

    def test_ordinary_leveraged_company_is_not_flagged(self):
        """6x is genuinely leveraged but perfectly meaningful. Flagging it
        would make the warning worthless through overuse."""
        self.assertEqual(self._caveats(DETERIORATING), [])

    def test_healthy_company_is_not_flagged(self):
        self.assertEqual(self._caveats(IMPROVING), [])

    def test_missing_leverage_produces_no_caveat(self):
        """Unknown is not implausible -- it must not trigger the warning."""
        rows = [(2024, 1000, 200, None, None, 20, 150, 50),
                (2025, 1000, 200, None, None, 20, 150, 50)]
        self.assertEqual(self._caveats(rows), [])


class TestRestructuringWatch(unittest.TestCase):
    """The Restructuring Watch must stay inside its remit: name questions,
    never predict default, and say plainly when there is nothing to flag."""

    def _watch(self, rows):
        h = _history(rows)
        metrics = M.compute_all_metrics(h)
        rating = rate_stress(metrics,
                             [(fy.year, fy.ebitda) for fy in h.sorted_years()])
        headline, items = restructuring_watch(
            rating, evaluate_signals(h, metrics), metrics)
        return rating, headline, items

    def test_low_stress_says_no_warning_signs(self):
        _, headline, items = self._watch(IMPROVING)
        self.assertIn("No immediate restructuring warning signs", headline)
        self.assertEqual(len(items), 1)

    def test_stressed_company_leads_with_maturities(self):
        """Timing is the biggest blind spot, so it must come first."""
        _, _, items = self._watch(DETERIORATING)
        self.assertEqual(items[0][0], "Upcoming debt maturities")
        areas = [a for a, _ in items]
        self.assertIn("Ability to refinance existing debt", areas)

    def test_stressed_company_names_its_drivers(self):
        rating, headline, _ = self._watch(DETERIORATING)
        self.assertIn("elevated", headline)
        self.assertIn("leverage", headline)

    def test_never_predicts_bankruptcy(self):
        """The one thing this section must never do."""
        for rows in (DETERIORATING, IMPROVING):
            _, headline, items = self._watch(rows)
            text = (headline + " " + " ".join(a + b for a, b in items)).lower()
            for forbidden in ("will default", "will go bankrupt",
                              "will file", "is insolvent",
                              "predict bankruptcy"):
                self.assertNotIn(forbidden, text)

    def test_negative_fcf_adds_liquidity_question(self):
        areas = [a for a, _ in self._watch(DETERIORATING)[2]]
        self.assertIn("Liquidity and cash availability", areas)


class TestSectorBenchmark(unittest.TestCase):
    """The cached peer benchmark used by the live app."""

    def _cache(self):
        return {
            "generated": "2026-10-18",
            "metrics": [
                {"key": "net_debt_to_ebitda", "label": "Net Debt / EBITDA",
                 "higherIsWorse": True},
                {"key": "interest_coverage", "label": "Interest Coverage",
                 "higherIsWorse": False},
            ],
            "sectors": {
                "Industrials": {
                    "tickers": ["AAA", "BBB", "CCC", "DDD", "EEE"],
                    "count": 5,
                    "values": {
                        "net_debt_to_ebitda": [1.0, 2.0, 3.0, 4.0, 5.0],
                        "interest_coverage": [10.0, 9.0, 8.0, 7.0, 6.0],
                    },
                },
                "Energy": {
                    "tickers": ["XOM"], "count": 1,
                    "values": {"net_debt_to_ebitda": [1.0],
                               "interest_coverage": [9.0]},
                },
            },
        }

    def _metrics(self, leverage, coverage):
        m = M.YearMetrics(year=2025)
        m.net_debt_to_ebitda = leverage
        m.interest_coverage = coverage
        return m

    def test_company_is_excluded_from_its_own_peer_group(self):
        """AAA is in the benchmark, so its own 1.0 must not shape the median.
        Median of the other four (2,3,4,5) is 3.5, not 3.0."""
        r = compare_to_sector("AAA", "Industrials",
                              self._metrics(1.0, 10.0), self._cache())
        self.assertTrue(r["available"])
        self.assertEqual(r["peerCount"], 4)
        self.assertNotIn("AAA", r["peerTickers"])
        lev = next(m for m in r["metrics"] if m["key"] == "net_debt_to_ebitda")
        self.assertAlmostEqual(lev["peerMedian"], 3.5)

    def test_company_outside_the_benchmark_is_still_compared(self):
        """The whole point: any ticker works, not only the cached ones."""
        r = compare_to_sector("NKE", "Industrials",
                              self._metrics(6.0, 2.0), self._cache())
        self.assertTrue(r["available"])
        self.assertEqual(r["peerCount"], 5)
        lev = next(m for m in r["metrics"] if m["key"] == "net_debt_to_ebitda")
        self.assertAlmostEqual(lev["peerMedian"], 3.0)
        self.assertAlmostEqual(lev["percentile"], 100.0)

    def test_too_few_peers_refuses_with_a_reason(self):
        r = compare_to_sector("XOM", "Energy",
                              self._metrics(1.0, 9.0), self._cache())
        self.assertFalse(r["available"])
        self.assertIn("at least", r["reason"])

    def test_unknown_sector_refuses_and_lists_what_is_covered(self):
        r = compare_to_sector("ZZZ", "Utilities",
                              self._metrics(3.0, 5.0), self._cache())
        self.assertFalse(r["available"])
        self.assertIn("Industrials", r["reason"])

    def test_missing_sector_refuses(self):
        r = compare_to_sector("ZZZ", None,
                              self._metrics(3.0, 5.0), self._cache())
        self.assertFalse(r["available"])
        self.assertIn("No sector", r["reason"])

    def test_missing_cache_raises_rather_than_looking_empty(self):
        with self.assertRaises(PeerCacheUnavailable):
            load_peer_cache("/nonexistent/peer_cache.json")

    def test_shipped_cache_loads_and_covers_sectors(self):
        """The committed benchmark must actually be usable."""
        cache = load_peer_cache()
        self.assertIn("sectors", cache)
        usable = [s for s, d in cache["sectors"].items() if d["count"] >= 4]
        self.assertTrue(usable, "no sector has enough peers to be usable")


class TestEdgarExtraction(unittest.TestCase):
    """The XBRL parsing, tested against synthetic fact data so these run
    offline and deterministically. Each test covers one way real filings
    break a naive parser."""

    def _fact(self, end, val, filed, start=None, form="10-K"):
        f = {"end": end, "val": val, "filed": filed, "form": form}
        if start:
            f["start"] = start
        return f

    def test_stale_tags_fall_through_to_the_current_one(self):
        """A company that switched tags must not return a series ending the
        year it switched. American Airlines last used LongTermDebtNoncurrent
        in 2012 and LongTermDebt since."""
        gaap = {
            "LongTermDebtNoncurrent": {"units": {"USD": [
                self._fact("2012-12-31", 100, "2013-02-01")]}},
            "LongTermDebt": {"units": {"USD": [
                self._fact("2024-12-31", 500, "2025-02-01"),
                self._fact("2025-12-31", 600, "2026-02-01")]}},
        }
        series, tags = edgar._annual_series(
            gaap, ["LongTermDebtNoncurrent", "LongTermDebt"], instant=True)
        self.assertEqual(series["2012-12-31"], 100)
        self.assertEqual(series["2025-12-31"], 600)
        self.assertEqual(len(tags), 2, "both tags should contribute")

    def test_higher_preference_tag_wins_a_contested_period(self):
        gaap = {
            "A": {"units": {"USD": [self._fact("2025-12-31", 111, "2026-02-01")]}},
            "B": {"units": {"USD": [self._fact("2025-12-31", 999, "2026-02-01")]}},
        }
        series, _ = edgar._annual_series(gaap, ["A", "B"], instant=True)
        self.assertEqual(series["2025-12-31"], 111)

    def test_quarterly_facts_are_excluded_from_annual_series(self):
        """Quarters and years share a tag. Counting a quarter as a year would
        understate revenue roughly fourfold."""
        gaap = {"Revenues": {"units": {"USD": [
            self._fact("2025-03-31", 25, "2025-05-01", start="2025-01-01"),
            self._fact("2025-12-31", 100, "2026-02-01", start="2025-01-01"),
        ]}}}
        series, _ = edgar._annual_series(gaap, ["Revenues"], instant=False)
        self.assertEqual(series, {"2025-12-31": 100.0})

    def test_restated_period_uses_the_most_recent_filing(self):
        """Every 10-K restates the prior year. The later filing is the
        company's latest word on that period."""
        gaap = {"Revenues": {"units": {"USD": [
            self._fact("2024-12-31", 900, "2025-02-01", start="2024-01-01"),
            self._fact("2024-12-31", 950, "2026-02-01", start="2024-01-01"),
        ]}}}
        series, _ = edgar._annual_series(gaap, ["Revenues"], instant=False)
        self.assertEqual(series["2024-12-31"], 950.0)

    def test_instant_facts_reject_durations_and_vice_versa(self):
        gaap = {"Cash": {"units": {"USD": [
            self._fact("2025-12-31", 50, "2026-02-01"),
            self._fact("2025-12-31", 77, "2026-02-01", start="2025-01-01"),
        ]}}}
        instant, _ = edgar._annual_series(gaap, ["Cash"], instant=True)
        self.assertEqual(instant, {"2025-12-31": 50.0})

    def test_non_annual_forms_are_ignored(self):
        gaap = {"Cash": {"units": {"USD": [
            self._fact("2025-09-30", 10, "2025-11-01", form="10-Q"),
            self._fact("2025-12-31", 20, "2026-02-01"),
        ]}}}
        series, _ = edgar._annual_series(gaap, ["Cash"], instant=True)
        self.assertEqual(series, {"2025-12-31": 20.0})

    def test_missing_tag_yields_empty_rather_than_raising(self):
        series, tags = edgar._annual_series({}, ["Nope"], instant=True)
        self.assertEqual(series, {})
        self.assertEqual(tags, [])

    def test_debt_parts_sum_across_periods(self):
        a = {"2025-12-31": 100.0, "2024-12-31": 90.0}
        b = {"2025-12-31": 10.0}
        self.assertEqual(edgar._sum_series(a, b),
                         {"2025-12-31": 110.0, "2024-12-31": 90.0})

    def test_fiscal_years_of_52_or_53_weeks_count_as_full(self):
        """Retailers' fiscal years are not 365 days. Rejecting them would
        blank the entire sector."""
        self.assertTrue(edgar._is_full_year(
            {"start": "2025-02-02", "end": "2026-01-31"}))
        self.assertFalse(edgar._is_full_year(
            {"start": "2025-01-01", "end": "2025-03-31"}))

    def test_user_agent_requires_a_contact_email(self):
        """The SEC refuses anonymous requests, so this must fail loudly rather
        than send an invented address."""
        saved = os.environ.pop("SEC_USER_AGENT", None)
        try:
            with self.assertRaises(edgar.EdgarError):
                edgar.user_agent()
            os.environ["SEC_USER_AGENT"] = "No Email Here"
            with self.assertRaises(edgar.EdgarError):
                edgar.user_agent()
            os.environ["SEC_USER_AGENT"] = "A Person a@example.com"
            self.assertIn("@", edgar.user_agent())
        finally:
            os.environ.pop("SEC_USER_AGENT", None)
            if saved is not None:
                os.environ["SEC_USER_AGENT"] = saved


class TestSourcesAreReachableEverywhere(unittest.TestCase):
    """Every data source the loader supports must also be reachable from the
    command line. These drifted apart once: EDGAR was wired into the loader
    and the web app, but main.py still rejected it as an invalid choice."""

    def _cli_choices(self):
        import main
        for action in main.build_parser()._actions:
            if "--source" in getattr(action, "option_strings", []):
                return set(action.choices or [])
        self.fail("main.py has no --source argument")

    def test_cli_accepts_every_supported_source(self):
        self.assertEqual(self._cli_choices(), {"local", "yfinance", "edgar"})

    def test_loader_accepts_every_cli_choice(self):
        """A choice the CLI offers must not be rejected by the loader. Each is
        called with a ticker that cannot resolve, so a DataLoadError is the
        expected outcome -- what must NOT appear is 'Unknown source'."""
        from screener.data_loader import DataLoadError, load_history
        for source in self._cli_choices():
            with self.subTest(source=source):
                try:
                    load_history("ZZZZNOTAREALTICKER", source=source)
                except DataLoadError as exc:
                    self.assertNotIn("Unknown source", str(exc))
                except Exception:
                    pass  # network or missing package: not what this tests


class TestAltmanZScore(unittest.TestCase):
    """The published Z''-score used as a second opinion on our own rating."""

    def _year(self, **kw):
        base = dict(year=2025, total_assets=1000.0, current_assets=400.0,
                    current_liabilities=200.0, retained_earnings=300.0,
                    operating_income=120.0, total_liabilities=500.0,
                    shareholders_equity=500.0)
        base.update(kw)
        return FiscalYear(**base)

    def test_formula_matches_altman_published_coefficients(self):
        """Worked by hand: WC/TA=0.2, RE/TA=0.3, EBIT/TA=0.12, EQ/TL=1.0
        -> 6.56(0.2) + 3.26(0.3) + 6.72(0.12) + 1.05(1.0)"""
        z = compute_z_score(self._year())
        expected = 6.56 * 0.2 + 3.26 * 0.3 + 6.72 * 0.12 + 1.05 * 1.0
        self.assertAlmostEqual(z.score, expected, places=6)
        self.assertEqual(z.zone, "Safe zone")

    def test_zones_follow_the_published_thresholds(self):
        self.assertEqual(altman.zone_for(2.61), "Safe zone")
        self.assertEqual(altman.zone_for(2.6), "Grey zone")
        self.assertEqual(altman.zone_for(1.1), "Grey zone")
        self.assertEqual(altman.zone_for(1.09), "Distress zone")
        self.assertEqual(altman.zone_for(None), "Not computable")

    def test_distressed_balance_sheet_scores_in_the_distress_zone(self):
        """Negative working capital, lifetime losses and negative equity --
        the American Airlines shape."""
        z = compute_z_score(self._year(
            current_assets=100.0, current_liabilities=400.0,
            retained_earnings=-200.0, shareholders_equity=-50.0,
            total_liabilities=1050.0, operating_income=20.0))
        self.assertLess(z.score, 1.1)
        self.assertEqual(z.zone, "Distress zone")

    def test_missing_balance_sheet_refuses_and_names_what_is_missing(self):
        z = compute_z_score(self._year(retained_earnings=None,
                                       total_assets=None))
        self.assertFalse(z.available)
        self.assertIn("retained earnings", z.reason)
        self.assertIn("total assets", z.reason)

    def test_zero_assets_refuses_rather_than_dividing(self):
        z = compute_z_score(self._year(total_assets=0.0))
        self.assertFalse(z.available)
        self.assertIn("assets", z.reason.lower())

    def test_zero_liabilities_refuses(self):
        z = compute_z_score(self._year(total_liabilities=0.0))
        self.assertFalse(z.available)

    def test_components_sum_to_the_score(self):
        """Every term shown must add up to the number displayed, or the
        breakdown is decoration rather than an explanation."""
        z = compute_z_score(self._year())
        total = sum(c["contribution"] for c in components(z))
        self.assertAlmostEqual(total, z.score, places=6)

    def test_components_empty_when_score_unavailable(self):
        self.assertEqual(components(compute_z_score(self._year(
            total_assets=None))), [])

    def test_banks_and_insurers_are_excluded(self):
        """Altman was never fitted on financial firms; their balance sheets
        do not carry the same meaning."""
        for sector in ("Financial Services", "Banks", "Insurance"):
            ok, reason = is_meaningful_for(sector)
            self.assertFalse(ok, sector)
            self.assertIn("Altman", reason)

    def test_industrial_sectors_are_allowed(self):
        for sector in ("Industrials", "Technology", None):
            ok, _ = is_meaningful_for(sector)
            self.assertTrue(ok)

    def test_the_rating_does_not_consult_the_z_score(self):
        """The Z-score must stay an independent cross-check. If rating.py ever
        imported it, 'two methods agreeing' would become circular."""
        import inspect
        from screener import rating as rating_module
        source = inspect.getsource(rating_module)
        self.assertNotIn("altman", source.lower())


class TestOfflineDataSupportsEveryFeature(unittest.TestCase):
    """The two synthetic companies are the demo fallback when there is no
    internet, so every section of the app must work with them. The Z-score
    silently did not, because those files carried only the core seven fields."""

    def test_synthetic_companies_produce_a_z_score(self):
        from screener.data_loader import load_history
        for ticker in ("EXMPL", "HEALTHY"):
            with self.subTest(ticker=ticker):
                history = load_history(ticker, source="local")
                z = compute_z_score(history.sorted_years()[-1])
                self.assertTrue(z.available,
                                f"{ticker} has no Z-score: {z.reason}")

    def test_synthetic_balance_sheets_balance(self):
        """Assets must equal liabilities plus equity, or the teaching data
        teaches something false."""
        from screener.data_loader import load_history
        for ticker in ("EXMPL", "HEALTHY"):
            for fy in load_history(ticker, source="local").years:
                with self.subTest(ticker=ticker, year=fy.year):
                    self.assertAlmostEqual(
                        fy.total_assets,
                        fy.total_liabilities + fy.shareholders_equity,
                        places=4)

    def test_the_deteriorating_company_ends_in_distress(self):
        """EXMPL exists to show deterioration, so its Z-score must fall."""
        from screener.data_loader import load_history
        scores = [compute_z_score(fy).score
                  for fy in load_history("EXMPL", source="local").sorted_years()]
        self.assertGreater(scores[0], scores[-1])
        self.assertEqual(altman.zone_for(scores[-1]), "Distress zone")

    def test_the_sound_company_stays_safe(self):
        from screener.data_loader import load_history
        scores = [compute_z_score(fy).score
                  for fy in load_history("HEALTHY", source="local").sorted_years()]
        self.assertTrue(all(altman.zone_for(s) == "Safe zone" for s in scores))


class TestEdgarTagCoverage(unittest.TestCase):
    """Filers choose among valid tags for the same concept, so the candidate
    lists have to be broad. Each tag below was added after a real company
    returned a blank field without it; these tests stop them being dropped."""

    def test_interest_covers_net_and_cash_paid_variants(self):
        """Delta tags neither InterestExpense nor InterestExpenseNonoperating;
        without the net and cash-paid fallbacks its coverage was blank."""
        for tag in ("InterestExpense", "InterestExpenseNonoperating",
                    "InterestIncomeExpenseNonoperatingNet", "InterestPaidNet"):
            self.assertIn(tag, edgar.INTEREST_TAGS)

    def test_capex_covers_the_other_productive_assets_variant(self):
        """Verizon's capex sits under this tag alone."""
        self.assertIn("PaymentsToAcquireOtherProductiveAssets",
                      edgar.CAPEX_TAGS)

    def test_pretax_fallback_exists_for_filers_without_operating_income(self):
        """IBM and Pfizer never tag OperatingIncomeLoss, so EBIT is rebuilt
        from pre-tax income plus interest -- the definition of EBIT read
        backwards."""
        self.assertTrue(edgar.PRETAX_INCOME_TAGS)

    def test_debt_includes_finance_leases(self):
        """Credit analysis treats finance leases as debt: they are fixed
        contractual payment obligations like any borrowing."""
        self.assertIn("LongTermDebtAndCapitalLeaseObligations",
                      edgar.LONG_TERM_DEBT_TAGS)
        self.assertIn("LongTermDebtAndCapitalLeaseObligationsCurrent",
                      edgar.CURRENT_DEBT_TAGS)

    def test_unparseable_filer_points_at_the_alternative_source(self):
        """A dead end must tell the reader what to do next, not just fail."""
        gaap = {"facts": {"us-gaap": {"SomethingUnrecognised": {"units": {}}}}}
        import unittest.mock as mock
        with mock.patch.object(edgar, "_get_json", return_value=gaap), \
             mock.patch.object(edgar, "ticker_to_cik", return_value=(1, "X")):
            with self.assertRaises(edgar.EdgarError) as caught:
                edgar.load_edgar_history("XXXX")
        self.assertIn("Yahoo", str(caught.exception))


class TestRatingTrajectory(unittest.TestCase):
    """The rating recomputed as of each past year."""

    def _history(self, rows):
        return _history_from(rows)

    def test_each_point_sees_only_data_up_to_that_year(self):
        """The whole claim is that these are point-in-time ratings rather than
        hindsight. If a point could see later years, trend-based factors would
        leak information a reader would not have had."""
        from screener.rating import rating_trajectory
        h = _history_from(DETERIORATING)
        points = rating_trajectory(h, M.compute_all_metrics)
        years = [fy.year for fy in h.sorted_years()]
        # One point per year except the first, which has no prior to trend from
        self.assertEqual([p.year for p in points], years[1:])

        # The earliest point must match a rating computed from that slice alone
        window = h.sorted_years()[:2]
        shell = _history_from([(fy.year, fy.revenue, fy.ebitda, fy.cash,
                                fy.total_debt, fy.interest_expense,
                                fy.operating_cash_flow, fy.capex)
                               for fy in window])
        standalone = rate_stress(
            M.compute_all_metrics(shell),
            [(fy.year, fy.ebitda) for fy in window])
        self.assertEqual(points[0].rating, standalone.rating)
        self.assertEqual(points[0].score, standalone.score)

    def test_deteriorating_company_shows_a_worsening_path(self):
        from screener.rating import rating_trajectory, trajectory_summary
        points = rating_trajectory(_history_from(DETERIORATING),
                                   M.compute_all_metrics)
        self.assertLess(points[0].ratio, points[-1].ratio)
        self.assertIn("worsened", trajectory_summary(points))

    def test_worsening_inside_one_band_is_still_reported(self):
        """A company can go from 69% to 85% of its stress points without
        changing band. Reporting only the unchanged label would hide that."""
        from screener.rating import rating_trajectory, trajectory_summary
        points = rating_trajectory(_history_from(DETERIORATING),
                                   M.compute_all_metrics)
        self.assertEqual(points[0].rating, points[-1].rating)
        summary = trajectory_summary(points)
        self.assertIn("throughout", summary)
        self.assertIn("worsened", summary)

    def test_a_band_crossing_is_named_with_its_year(self):
        """Five years of EXMPL cross from Low into Elevated."""
        from screener.data_loader import load_history
        from screener.rating import rating_trajectory, trajectory_summary
        points = rating_trajectory(load_history("EXMPL", source="local"),
                                   M.compute_all_metrics)
        summary = trajectory_summary(points)
        self.assertIn("deteriorated", summary)
        self.assertIn("crossed in", summary)

    def test_stable_company_reports_no_change(self):
        from screener.rating import rating_trajectory, trajectory_summary
        points = rating_trajectory(_history_from(IMPROVING),
                                   M.compute_all_metrics)
        self.assertIn("throughout", trajectory_summary(points))

    def test_single_year_yields_no_trajectory(self):
        from screener.rating import rating_trajectory, trajectory_summary
        points = rating_trajectory(_history_from(DETERIORATING[:1]),
                                   M.compute_all_metrics)
        self.assertEqual(points, [])
        self.assertIn("Not enough history", trajectory_summary(points))


class TestMaturitySchedule(unittest.TestCase):
    """The debt maturity ladder: the gap the project's own report named first."""

    def _schedule(self, amounts):
        from screener.models import MaturityBucket, MaturitySchedule
        labels = ["Within 1 year", "Year 2", "Year 3", "Year 4", "Year 5",
                  "After 5 years"]
        return MaturitySchedule(
            as_of_year=2025,
            buckets=[MaturityBucket(label=l, amount=a)
                     for l, a in zip(labels, amounts)])

    def test_total_sums_only_the_tagged_rungs(self):
        s = self._schedule([100.0, 200.0, None, 50.0, None, None])
        self.assertAlmostEqual(s.total, 350.0)

    def test_untagged_rungs_are_not_counted_as_zero(self):
        """A rung the filing did not tag is unknown, not nil. Counting it as
        zero would understate the schedule while looking complete."""
        s = self._schedule([100.0, None, None, None, None, None])
        self.assertAlmostEqual(s.total, 100.0)
        self.assertIsNone(s.buckets[1].amount)

    def test_fully_untagged_schedule_has_no_total(self):
        self.assertIsNone(self._schedule([None] * 6).total)

    def test_nearest_rung_is_exposed_separately(self):
        """The within-one-year figure is the one that drives the analysis."""
        s = self._schedule([3641.0, 4455.0, None, None, None, None])
        self.assertAlmostEqual(s.due_within_one_year, 3641.0)

    def test_non_edgar_sources_carry_no_schedule(self):
        """Only EDGAR supplies maturities; others must leave it None rather
        than inventing one."""
        from screener.data_loader import load_history
        self.assertIsNone(load_history("EXMPL", source="local").maturities)


class TestAppImportsCleanly(unittest.TestCase):
    """app.py must at least import without error.

    This gap let a NameError reach the browser: LOW_CEILING was used at module
    level but never imported, and nothing in the suite loaded app.py, so every
    test passed against a page that crashed on sight.
    """

    def test_app_module_imports(self):
        import importlib
        import app  # noqa: F401
        importlib.reload(app)

    def test_every_name_app_uses_from_rating_is_importable(self):
        """Catches the specific failure above: a name used in app.py that
        rating.py does not actually export."""
        import ast
        import screener.rating as rating_module
        tree = ast.parse(open("app.py", encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "screener.rating":
                for alias in node.names:
                    self.assertTrue(hasattr(rating_module, alias.name),
                                    f"rating.py does not export {alias.name}")


class TestMarkdownMoneyEscaping(unittest.TestCase):
    """Streamlit parses prose as Markdown, where a pair of dollar signs
    delimits LaTeX math. Two currency figures in one sentence turned the text
    between them into a mangled equation on the live page."""

    def test_money_in_prose_escapes_the_dollar_sign(self):
        import app
        from screener.models import FinancialHistory
        h = FinancialHistory(ticker="X", company_name="X", currency="USD",
                             units="millions")
        self.assertEqual(app.md_money(3641.0, h), r"\$3.6bn")
        self.assertEqual(app.md_money(-680.0, h), r"-\$680m")

    def test_metric_formatting_is_left_unescaped(self):
        """st.metric does not parse Markdown, so escaping there would print
        a stray backslash."""
        import app
        from screener.models import FinancialHistory
        h = FinancialHistory(ticker="X", company_name="X", currency="USD",
                             units="millions")
        self.assertEqual(app.fmt_money(3641.0, h), "$3.6bn")
        self.assertNotIn("\\", app.fmt_money(3641.0, h))


class TestMarketScanDataset(unittest.TestCase):
    """The pre-screened benchmark set behind the market scan."""

    def _scan(self):
        import json
        with open("data/market_scan.json", encoding="utf-8") as fh:
            return json.load(fh)

    def test_every_company_carries_a_rating_and_a_rank(self):
        for row in self._scan()["companies"]:
            with self.subTest(ticker=row["ticker"]):
                self.assertIn(row["rating"],
                              (LOW, MODERATE, ELEVATED, "Insufficient Data"))
                self.assertGreaterEqual(row["rank"], 1)

    def test_ranking_is_worst_first(self):
        """The ordering is the point: a rank that does not track the score
        would make the whole scan misleading."""
        rows = self._scan()["companies"]
        ratios = [r["ratio"] or 0 for r in rows]
        self.assertEqual(ratios, sorted(ratios, reverse=True))

    def test_scores_match_their_stated_band(self):
        """A row labelled Elevated must actually clear the Elevated cut-off,
        or the scan and the screener disagree."""
        from screener.rating import LOW_CEILING, MODERATE_CEILING
        for row in self._scan()["companies"]:
            ratio = row["ratio"]
            if ratio is None:
                continue
            with self.subTest(ticker=row["ticker"]):
                expected = (LOW if ratio < LOW_CEILING
                            else MODERATE if ratio < MODERATE_CEILING
                            else ELEVATED)
                self.assertEqual(row["rating"], expected)

    def test_sector_medians_need_at_least_three_companies(self):
        """A median built from two is an anecdote."""
        scan = self._scan()
        counts = {}
        for row in scan["companies"]:
            if row["sector"]:
                counts[row["sector"]] = counts.get(row["sector"], 0) + 1
        for sector in scan.get("sectorMedians", {}):
            self.assertGreaterEqual(counts.get(sector, 0), 3, sector)

    def test_synthetic_companies_are_absent(self):
        """Invented figures must never enter a real benchmark."""
        tickers = {r["ticker"] for r in self._scan()["companies"]}
        self.assertNotIn("EXMPL", tickers)
        self.assertNotIn("HEALTHY", tickers)
