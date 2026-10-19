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

from screener import metrics as M                                   # noqa: E402
from screener.models import FinancialHistory, FiscalYear            # noqa: E402
from screener.narrative import (restructuring_watch,                # noqa: E402
                                structural_caveats)
from screener.peers import (PeerCacheUnavailable,                   # noqa: E402
                            compare_to_peers, compare_to_sector,
                            load_peer_cache, median)
from screener.rating import ELEVATED, LOW, rate_stress              # noqa: E402
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
