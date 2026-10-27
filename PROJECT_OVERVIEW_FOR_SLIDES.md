# Project briefing — paste this into a new Claude conversation

> Copy everything below the line into a fresh Claude chat, then ask it to help
> you build your slide deck. It has no other context, so this document is
> written to stand alone.

---

I built a software project for a college Big Data course and I need help making
a slide deck about it. Here is everything about the project.

## What it is

**Credit Health & Restructuring Watch Agent** — a web application that screens
public companies for signs of credit deterioration.

- Live app: https://restructuring-watch.streamlit.app
- Code: https://github.com/gomeslice-tech69/Credit-Health-AI-Agent-Take-2-
- Built in Python with Streamlit. 10,500 lines, 155 unit tests, 20 commits.

## The question it answers

> Is this company's credit profile improving or deteriorating, and are there
> warning signs that could eventually require restructuring analysis?

It is a **first-pass screening tool**. It does not predict bankruptcy, is not
investment advice, and does not design restructuring plans. Its job is to sort
a long list of companies into "look harder" and "move on".

## How it works — the pipeline

```
Ticker
  → Financial data   (3 sources: Yahoo Finance, SEC EDGAR, offline files)
  → Credit metrics   (6 ratios computed per year)
  → Signal detection (7 warning signs)
  → Stress test      (what if EBITDA falls 20%?)
  → Peer comparison  (vs sector median)
  → Rating           (Low / Moderate / Elevated)
  → Explanation      (plain language)
```

**The central design rule: Python performs every calculation and decides the
rating. The explanation layer only describes the result — it never touches a
number.** The same ticker produces byte-identical output on every run.

## The finance

Seven reported figures per company per year: revenue, EBITDA, cash, total
debt, interest expense, operating cash flow, capital expenditure.

Six metrics computed from them:

| Metric | Formula | Meaning |
|---|---|---|
| Debt / EBITDA | Total Debt ÷ EBITDA | Years of earnings to repay all debt |
| Net Debt / EBITDA | (Total Debt − Cash) ÷ EBITDA | Same, crediting cash held |
| Interest Coverage | EBITDA ÷ Interest Expense | Times over the interest bill is covered |
| Free Cash Flow | Operating Cash Flow − Capex | Cash genuinely left over |
| EBITDA Margin | EBITDA ÷ Revenue | Operating earnings per dollar of sales |
| Revenue Growth | (Rev_t ÷ Rev_t−1) − 1 | Top-line direction |

**Why these three matter together:** leverage measures the *size* of the
problem, interest coverage measures its *urgency* (missing a payment is an
event of default), and free cash flow measures whether the situation is
*self-correcting or worsening*.

## The rating — five factors, no machine learning

| Factor | Max points | Captures |
|---|---|---|
| Leverage level | 3 | Size of the problem |
| Leverage trend | 2 | Direction of travel |
| Interest coverage | 3 | Urgency |
| Free cash flow | 3 | Self-funding or not |
| EBITDA trend | 2 | The engine driving the rest |

Thresholds (these are real credit conventions, written down explicitly):

```
Leverage level     Net Debt/EBITDA:  <2.0x=0,  2.0-4.0x=1,  4.0-6.0x=2,  >6.0x=3
Leverage trend     change first→last: improving/flat=0, worse <1.0x=1, worse ≥1.0x=2
Interest coverage  EBITDA/interest:  >6.0x=0,  3.0-6.0x=1,  1.5-3.0x=2,  <1.5x=3
Free cash flow     positive both years=0, positive latest only=1,
                   negative latest=2, negative both=3
EBITDA trend       change first→last: growing/flat=0, down <10%=1, down ≥10%=2
```

Points are summed and divided by the maximum that could *actually be
assessed*, so a company with patchy disclosure is not flattered by the gaps.
Below 30% = Low, 30–60% = Moderate, above 60% = Elevated.

**Deliberately rules rather than a fitted model**, for three reasons:
1. Every point is explainable — you can name which threshold produced it.
2. The thresholds *are* the finance, written down rather than buried in weights.
3. Corporate bankruptcies are rare, so a model fitted on a few hundred learns
   the quirks of that sample rather than a general rule.

## The application — six tabs

1. **Company** — screen any public ticker. Sub-tabs: Verdict, Trends, Risk,
   What next. Includes a rating trajectory (the rating recomputed as of each
   past year, from a truncated history so there is no hindsight), charts with
   the credit bands shaded in, an interactive stress-test slider, and a debt
   maturity wall.
2. **Market scan** — 484 companies screened against identical thresholds and
   ranked worst-first, filterable by sector and rating band, with sector
   medians.
3. **Industry watch** — three sub-tabs:
   - *Briefing*: a counted summary of the market (filings this period vs last,
     which 8-K items fired, which industries, press themes)
   - *SEC filings*: live restructuring events from SEC full-text search —
     Chapter 11 petitions, restructuring support agreements, going-concern
     warnings, forbearance agreements, DIP financing
   - *Press coverage*: headlines from 13 publishers' public RSS feeds (WSJ,
     NYT DealBook, Bloomberg, FT, CNBC) filtered to credit and restructuring
4. **Learn** — a 15-question quiz on private credit and restructuring
   fundamentals, with explanations for why each wrong answer is wrong.
5. **Methodology** — the rating logic, with a sandbox where you set each of
   the five factors yourself and watch the band move.
6. **About** — what the tool is, what it can't see.

## Project metrics — hard numbers for the deck

### Data processed

| | |
|---|---|
| Companies screened | **484** |
| Sectors covered | 10 |
| Company-years analysed | **2,294** |
| Raw financial figures ingested | **~16,000** |
| Rating distribution | 71 Elevated · 122 Moderate · 291 Low |
| Dataset size | 470 KB (committed, loads with zero network calls) |

### Engineering

| | |
|---|---|
| Lines of Python | **10,500** across 25 files |
| Unit tests | **155** in 26 test classes |
| Test code | 1,377 lines — roughly 1 line of test per 7 of source |
| Documentation in code | 274 docstrings, 583 comment lines |
| Git commits | 20 |

### Scope

| | |
|---|---|
| Data sources | **3** — Yahoo Finance (live), SEC EDGAR XBRL (official), offline synthetic |
| XBRL tag variants handled | **40** — filers use different tags for the same concept |
| EDGAR extraction coverage | 30 of 34 companies tested |
| News feeds aggregated | **13** publishers (WSJ, NYT, Bloomberg, FT, CNBC, SEC, Fed) |
| SEC event categories tracked | 5 (Ch11, RSAs, going concern, forbearance, DIP) |
| Quiz questions | 15 across 4 topics, 3 difficulty levels |
| Application tabs | 6, plus 7 sub-tabs |

### Numbers worth saying out loud

- **484 companies screened against identical thresholds.** Ask a person — or a
  chatbot — about 484 companies and you get 484 incomparable answers.
- **2,294 company-years** of financial history processed.
- **155 tests, most of them about missing or malformed data** rather than
  happy-path arithmetic. That ratio is deliberate: in financial software the
  dangerous failure is not a crash, it is a plausible wrong number.
- **40 XBRL tag variants** needed to read 30 of 34 companies. American
  Airlines last used one of them in 2012 and has used a different one since —
  a single tag list would have returned a series ending fourteen years ago.
- **Zero network calls at page load.** The entire 484-company scan is
  precomputed and committed, so the app is fast and cannot be rate-limited.

## Three findings — the most interesting part of the project

All three are cases where **the arithmetic was correct and the interpretation
was wrong.** This is the characteristic failure mode of financial software,
and none would be caught by testing the calculations. Each was found by
looking at real output for a company where the answer was already known to be
implausible.

### 1. Ford screens at 39x leverage — and isn't in distress

Ford Credit's borrowing sits on Ford's balance sheet, but the interest income
that loan book earns is **not** in EBITDA. So the numerator counts the finance
debt while the denominator ignores the finance earnings. Banks, insurers and
leasing companies produce the same distortion.

A blank cell announces itself; a confidently printed "39.14x" does not. The
tool now flags any reading above 15x *above* the number, explains the
mechanism, and says what a real analyst does instead (split the industrial
segment out using 10-K segment disclosures).

### 2. "Total debt" is a definition, not a fact

American Airlines screens **Elevated** on Yahoo Finance data and **Moderate**
on SEC EDGAR data. Same company, same fiscal year, same formula.

| Source | AAL 2025 total debt |
|---|---|
| Yahoo Finance | 36,884m |
| SEC EDGAR | 29,007m |

The ~7,900m gap is **operating lease liabilities** — Yahoo includes them, the
EDGAR implementation does not. Neither is wrong. But the input definition
alone moves the verdict a whole band, which is why professionals state their
definitions and why every report in the app names its source.

### 3. The tool had to learn to refuse

Screening Goldman Sachs produced a rating. It should have produced a refusal.

| Goldman Sachs FY2025 | |
|---|---|
| Revenue | 58,283 |
| Interest expense | **66,814** |
| EBITDA | not reported |
| Operating cash flow | **−45,154** |

None of that is distress. A bank borrows **in order to lend** — deposits and
funding are raw material, not capital structure. Interest expense sits closer
to cost of goods sold than to a financing cost, which is why it exceeds
revenue and why no bank reports EBITDA: *earnings before interest* is not a
meaningful quantity for a lender. The negative operating cash flow is a
growing loan book.

The screener nonetheless awarded **three of three stress points** for "a
sustained cash shortfall". It now classifies every company before scoring
anything: banks, insurers and asset managers are refused outright with an
explanation naming what *is* used instead (CET1 ratios, net interest margin,
loan loss provisions, liquidity coverage). REITs and utilities are rated with
a warning that the thresholds are calibrated for industrials. 24 financial
companies were also removed from the peer benchmark, where their funding
profile was silently corrupting the medians for every manufacturer beside
them.

## What makes this different from just asking an AI chatbot

This is the key argument of the project. A chat answer is a **judgment**; this
is an **instrument**. Different kinds of object.

- **Reproducible.** Same ticker, identical output every run — rating, score,
  wording and all. A chatbot gives a different answer each time, and neither
  is checkable.
- **It cannot invent a number.** Every figure comes from a tested function
  reading a reported line item.
- **It refuses.** Negative EBITDA produces "not meaningful" rather than a
  flattering negative multiple. Untagged debt reports as unavailable rather
  than zero. Banks are not rated at all.
- **One ruler.** All 484 benchmark companies meet identical thresholds across
  2,294 company-years, so the rankings actually compare. Ask a chatbot about
  484 companies and you get 484 incomparable answers.
- **It shows its work.** Every rating point maps to a written threshold; every
  EDGAR figure names the XBRL tag it came from.

The honest framing is not "mine is better." It is: *a screen's job is to be
consistent, reproducible and auditable across many companies so a human can
decide where to spend judgment. That is a different job from answering one
question well — and it is the job that scales.*

## Technical details worth mentioning

- **SEC EDGAR XBRL parsing** was the hardest part. Three traps in raw filings:
  tags go stale (American Airlines last used `LongTermDebtNoncurrent` in 2012),
  every 10-K restates the prior year so the same period appears in multiple
  filings, and quarterly facts share a tag with annual ones (counting a
  quarter as a year understates revenue fourfold). Coverage reached 30 of 34
  companies tested.
- **Caching** matters for reliability, not just speed: Yahoo rate-limits
  repeated requests, far more aggressively against shared cloud hosts.
- **The news filter had a real bug.** Matching keywords as plain substrings
  looked correct and was quietly wrong — `lbo` matched "Dea**lbo**ok", `clo`
  matched "neo**clo**ud", and personal-finance advice columns matched on
  "debt". Fixed with word-boundary matching in two tiers.
- **Deployment** is automatic: push to GitHub and Streamlit Cloud rebuilds.

## Limitations — be upfront about these

1. **Financial companies cannot be screened at all.** Different toolkit
   entirely.
2. **Covenant levels are invisible** — often what actually triggers a
   restructuring.
3. **Undrawn credit facilities are invisible** — the difference between a
   problem and a crisis.
4. **Cyclical vs structural decline** — the judgement that matters most, and
   no ratio answers it.
5. **EBITDA quality** — reported figures may carry generous add-backs, and
   every ratio rests on that denominator.
6. **Annual data only** — a company can deteriorate fast inside a fiscal year.
7. **Debt maturities only from SEC EDGAR**, and only where the filer tagged
   them.
8. **Thresholds are not validated against outcomes.** They are defensible
   conventions, not backtested rules. (Planned next step: run the screen on
   companies' final pre-bankruptcy filings and report how many it flagged.)

## What I want from you

Help me build a slide deck about this project for a college class
presentation. Ask me about length, audience and format before you start if
that would help.
