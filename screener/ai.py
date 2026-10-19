"""
OPTIONAL Claude layer: rewording the explanation more fluently.

THE APP WORKS COMPLETELY WITHOUT THIS FILE. By default the dashboard uses
narrative.py, which builds prose from sentence templates chosen by the computed
facts. That is deterministic and free. This module is an upgrade, not a
dependency.

WHAT IT DOES AND DOES NOT DO

It receives the facts that Python already computed, as a block of text, and
asks Claude to rewrite them as flowing prose for a reader learning finance.

It does NOT:
  - calculate anything
  - decide the stress rating
  - have access to the internet or to any data beyond the facts passed in

That boundary is the point of the project's architecture, and it is enforced
in two places: the system prompt below instructs Claude to use only the given
numbers, and the facts block is the ONLY content sent. Claude cannot alter a
ratio because it never sees the inputs or does the division.

Being precise about this matters when you present the project. Even with this
enabled, the numbers, the signals and the rating come from Python and are
reproducible. Claude changes the wording only.

SETUP

    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

Then tick "Use Claude for explanations" in the sidebar. Without a key, the app
silently stays in template mode and says so in the sidebar.

COST: each explanation is a short request -- roughly 1,500 input tokens and 500
output tokens, so a fraction of a cent per company at current Claude Opus 5.5
pricing. The result is cached per ticker for the session so moving the downside
slider does not trigger new requests.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .metrics import YearMetrics
from .models import FinancialHistory
from .narrative import Narrative
from .rating import StressRating
from .signals import Signal

MODEL = "claude-opus-5-5"

# The instruction that keeps the language model inside its lane.
SYSTEM_PROMPT = """You explain corporate credit analysis to a university \
student who is new to investment banking and restructuring.

You will be given financial facts that have already been calculated. Write a \
clear explanation of what they show.

ABSOLUTE RULES:
- Use ONLY the numbers given to you. Never introduce a figure that is not in \
the facts, never estimate, and never round in a way that changes meaning.
- Never contradict the stress rating you are given. It was computed by a \
transparent rule set. Explain it; do not re-judge it.
- If a fact is marked unavailable, say it is unavailable. Do not guess.
- Never predict bankruptcy or default, and never give investment advice. This \
is a screening tool that identifies what an analyst should investigate.
- No single metric proves a company is in trouble. Where you flag a concern, \
make clear it is a warning sign warranting investigation.

STYLE:
- Plain language. Define a term the first time you use it, briefly.
- Explain WHY a metric moved, not just that it moved.
- Two or three short paragraphs. No headings, no bullet points, no preamble.
- Write in the third person about the company. Do not address the reader."""


class AIUnavailable(Exception):
    """Raised when the Claude path cannot be used. The caller falls back to
    template mode and shows this message, so it must read cleanly in the UI."""


def is_configured() -> bool:
    """True when both the SDK and a key are present.

    Note this does not prove the key is valid -- only a real request can. The
    app surfaces an invalid key as a warning and falls back.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def status_message() -> str:
    """Human-readable explanation of the current mode, for the sidebar."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return ("The `anthropic` package is not installed, so explanations use "
                "the built-in template writer. Install it with "
                "`pip install anthropic` to enable Claude.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ("No ANTHROPIC_API_KEY is set, so explanations use the built-in "
                "template writer. Set the environment variable to enable "
                "Claude.")
    return "Claude is available for explanations."


def build_facts_block(history: FinancialHistory,
                      metrics: List[YearMetrics],
                      signals: List[Signal],
                      rating: StressRating) -> str:
    """Serialise the computed facts into the text sent to Claude.

    Everything here was computed by Python. This function is deliberately dull:
    it formats, it does not calculate. Read it to see exactly what the model is
    told -- there is nothing else.
    """
    lines = [
        f"COMPANY: {history.company_name} (ticker {history.ticker})",
        f"CURRENCY AND UNITS: {history.currency}, {history.units}",
        f"DATA SOURCE: {history.source}",
        "",
        "REPORTED FIGURES AND COMPUTED RATIOS BY FISCAL YEAR:",
    ]

    years = {fy.year: fy for fy in history.sorted_years()}
    for m in metrics:
        fy = years[m.year]

        def num(value: Optional[float], fmt: str = ",.0f") -> str:
            return "unavailable" if value is None else format(value, fmt)

        lines.append(
            f"  {m.year}: revenue {num(fy.revenue)}, EBITDA {num(fy.ebitda)}, "
            f"cash {num(fy.cash)}, total debt {num(fy.total_debt)}, "
            f"interest expense {num(fy.interest_expense)}, "
            f"operating cash flow {num(fy.operating_cash_flow)}, "
            f"capex {num(fy.capex)}")
        lines.append(
            f"        Debt/EBITDA {num(m.debt_to_ebitda, '.2f')}x, "
            f"Net Debt/EBITDA {num(m.net_debt_to_ebitda, '.2f')}x, "
            f"interest coverage {num(m.interest_coverage, '.2f')}x, "
            f"free cash flow {num(m.free_cash_flow)}, "
            f"EBITDA margin {num(m.ebitda_margin, '.1%')}")

    lines += ["", "WARNING SIGNALS CHECKED:"]
    for s in signals:
        label = {"fired": "TRIGGERED", "clear": "not triggered",
                 "unknown": "could not assess"}[s.status]
        lines.append(f"  [{label}] {s.name}: {s.detail}")

    lines += ["", f"STRESS RATING (computed by rules, not by you): "
                  f"{rating.rating}"]
    if rating.ratio is not None:
        lines.append(f"  Score {rating.score} of {rating.max_score} possible "
                     f"stress points ({rating.ratio:.0%}).")
    lines.append("  Factor breakdown:")
    for f in rating.factors:
        points = "not assessed" if f.points is None else \
                 f"{f.points}/{f.max_points} points"
        lines.append(f"    {f.name} - {points}: {f.observation}")

    if history.notes:
        lines += ["", "DATA CONSTRUCTION NOTES:"]
        for key, note in sorted(history.notes.items()):
            lines.append(f"  {key}: {note}")

    return "\n".join(lines)


def explain(history: FinancialHistory,
            metrics: List[YearMetrics],
            signals: List[Signal],
            rating: StressRating,
            fallback: Narrative) -> Narrative:
    """Ask Claude to reword the explanation. Falls back on any failure.

    Returns a Narrative with mode="claude" on success. Raises AIUnavailable
    with a UI-readable message on failure, so the caller can show why it fell
    back rather than silently degrading.

    Note what is NOT replaced: rating_reasons and analyst_questions stay as
    Python generated them. The rating's justification must remain a mechanical
    restatement of the scored factors, and the analyst checklist is a curated
    teaching list. Only the two free-prose paragraphs are rewritten.
    """
    try:
        import anthropic
    except ImportError:
        raise AIUnavailable(
            "The `anthropic` package is not installed. Run "
            "`pip install anthropic`.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AIUnavailable(
            "No ANTHROPIC_API_KEY environment variable is set.")

    facts = build_facts_block(history, metrics, signals, rating)
    request = (
        f"{facts}\n\n"
        "Write two sections, separated by a line containing only '---'.\n\n"
        "Section 1 (2-3 short paragraphs): what is happening to this "
        "company's financial position, and why the metrics moved the way they "
        "did.\n\n"
        "Section 2 (1 short paragraph): why this matters -- what reduced "
        "financial flexibility would mean for the company if conditions got "
        "worse.\n\n"
        "Output only those two sections and the separator."
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            # Deliberately short output: this is a rewording task, and a tight
            # ceiling keeps cost and latency low.
            max_tokens=2000,
            # "low" effort suits a straightforward rewording job. Raise it if
            # you later ask Claude to do genuine analysis rather than wording.
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": request}],
        )
    except anthropic.AuthenticationError:
        raise AIUnavailable(
            "The ANTHROPIC_API_KEY was rejected. Check that it is correct.")
    except anthropic.RateLimitError:
        raise AIUnavailable("Rate limited by the Claude API. Try again shortly.")
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"The Claude API returned an error: {exc.message}")
    except anthropic.APIConnectionError:
        raise AIUnavailable(
            "Could not reach the Claude API. Check your internet connection.")

    # A safety stop means no usable prose came back; fall back rather than
    # showing an empty section.
    if response.stop_reason == "refusal":
        raise AIUnavailable(
            "Claude declined to answer this request. Using the built-in "
            "explanation instead.")

    text = "".join(block.text for block in response.content
                   if block.type == "text").strip()
    if not text:
        raise AIUnavailable("Claude returned an empty response.")

    # Split on the separator. If the model did not use it, treat the whole
    # response as section 1 and keep the template's "why it matters".
    if "---" in text:
        part1, part2 = text.split("---", 1)
        what, why = part1.strip(), part2.strip()
    else:
        what, why = text, fallback.why_it_matters

    return Narrative(
        headline=fallback.headline,
        what_is_happening=what,
        why_it_matters=why or fallback.why_it_matters,
        scenario_explanation=fallback.scenario_explanation,
        rating_reasons=fallback.rating_reasons,       # rules, not prose
        analyst_questions=fallback.analyst_questions,  # curated list
        mode="claude",
    )
