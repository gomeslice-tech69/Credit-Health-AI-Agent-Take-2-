# Credit Health & Restructuring Watch Agent

**Big Data Project — Rough Draft**

Date: 19 October 2026
Live demo: https://restructuring-watch.streamlit.app
Code: https://github.com/gomeslice-tech69/Credit-Health-AI-Agent-Take-2-

> **Status: rough draft.** The analytical engine, the web interface, the test
> suite and the peer-comparison component are complete and working in both the
> live app and the hosted version. Section 13 lists what I plan to extend next.

---

## 1. Research question

The project answers one question about a public company:

> **Is this company's credit profile improving or deteriorating, and are there
> warning signs that could eventually require restructuring analysis?**

It is a *screening* tool. Its purpose is to sort a long list of companies into
"look harder" and "move on" — not to predict bankruptcy, and not to design a
restructuring. Both of those would be far beyond what seven annual figures per
company can support.

## 2. What the system does

Given a stock ticker, it:

1. Retrieves up to five years of seven reported figures — revenue, EBITDA,
   cash, total debt, interest expense, operating cash flow, capital
   expenditure.
2. Computes six standard credit metrics for each year.
3. Checks seven warning signals by comparing the earliest year to the latest.
4. Runs a downside stress test (what if EBITDA falls by 20%?).
5. Scores the result against published thresholds and assigns a rating of
   **Low**, **Moderate** or **Elevated** credit stress.
6. Explains the result in plain language and lists what an analyst should
   investigate next.

## 3. Design principle

**Python performs every calculation. The language model only describes the
result.**

This is the central architectural decision of the project, and it has three
consequences I can defend:

| | |
|---|---|
| **Reproducibility** | Every figure is identical on every run. A project where a language model does arithmetic cannot promise this. |
| **Auditability** | Every number traces to a named function; every stress point traces to a written threshold. |
| **Independence** | The default explanation mode uses no language model at all. The AI layer is optional and additive. |

A second rule governs missing data:

> **A figure that could not be obtained is `None`. It is never zero, and it is
> never estimated.**

Zero and unknown mean different things in credit analysis — zero debt is
excellent news, unknown debt means no view can be formed. The code propagates
`None` through every calculation and the interface displays "n/a" with a stated
reason. A tool that silently invents inputs produces confident nonsense, which
is worse than producing nothing.

### A note on the explanation layer

The explanations are written by Python, not by a language model. An optional
Claude layer exists in `screener/ai.py` and can reword the same computed
figures, but it is not enabled, and the project is better for it: identical
inputs produce identical wording on every run, which is part of the
reproducibility claim above rather than a limitation of it.

Claude never had access to the arithmetic in either configuration. It receives
figures Python has already computed and is instructed to introduce none of its
own. Leaving it off removes the question entirely.

## 4. Architecture

Four stages, each in its own module, each independently testable. Two
interfaces share all of it.

```
    TICKER
      |
      v
+-----------------+   STAGE 1: ACQUISITION
|  data_loader.py |   Yahoo Finance (live) or local JSON (offline)
+-----------------+   Missing -> None, never guessed
      |
      v  FinancialHistory
+-----------------+   STAGE 2: CALCULATION  (pure Python, no AI)
|   metrics.py    |   six credit ratios, per year
|   signals.py    |   seven warning signals
|   scenario.py   |   EBITDA downside stress test
|   rating.py     |   five scored factors -> Low / Moderate / Elevated
+-----------------+
      |
      v
+-----------------+   STAGE 3: EXPLANATION
|  narrative.py   |   prose assembled from the computed facts (default)
|     ai.py       |   optional: Claude rewords it, never recalculates
+-----------------+
      |
      +--------------------+
      v                    v
+-------------+     +-------------+   STAGE 4: PRESENTATION
|  report.py  |     |   app.py    |   formatting only, no arithmetic
|   (text)    |     | (dashboard) |
+-------------+     +-------------+
```

The command-line tool and the web dashboard call the same functions, so their
figures cannot disagree. The finance can be tested without a browser, and the
interface can be rebuilt without endangering the finance.

## 5. The credit metrics

| Metric | Formula | Interpretation |
|---|---|---|
| Debt / EBITDA | `Total Debt / EBITDA` | Years of EBITDA needed to repay all borrowings |
| Net Debt / EBITDA | `(Total Debt - Cash) / EBITDA` | The same, crediting cash already held |
| Interest Coverage | `EBITDA / Interest Expense` | Times over the interest bill is covered |
| Free Cash Flow | `Operating Cash Flow - Capex` | Cash genuinely left over |
| EBITDA Margin | `EBITDA / Revenue` | Operating earnings per dollar of sales |
| Revenue Growth | `(Rev_t / Rev_t-1) - 1` | Year-over-year change in the top line |

**Why these three together.** Leverage measures the *size* of the problem;
interest coverage measures its *urgency*; free cash flow measures whether the
situation is *self-correcting or deteriorating*. High leverage is survivable
for years if coverage is comfortable and cash flow is positive. The dangerous
combination is high leverage **and** thin coverage **and** negative free cash
flow — then debt grows while the capacity to service it shrinks.

Negative free cash flow funded by new borrowing is the most common path into
distress: leverage rises mechanically year after year, with no single dramatic
event.

## 6. The rating method

Five factors, each scored against fixed published thresholds. Points are summed
and divided by the maximum that could actually be assessed.

| Factor | Max points | Captures |
|---|---|---|
| Leverage level | 3 | the size of the problem |
| Leverage trend | 2 | the direction of travel |
| Interest coverage | 3 | the urgency |
| Free cash flow | 3 | self-funding or not |
| EBITDA trend | 2 | the engine driving the rest |

```
Leverage level     Net Debt/EBITDA:  <2.0x = 0,  2.0-4.0x = 1,  4.0-6.0x = 2,  >6.0x = 3
Leverage trend     change earliest->latest:  improving/flat = 0,  worse <1.0x = 1,  worse >=1.0x = 2
Interest coverage  EBITDA/interest:  >6.0x = 0,  3.0-6.0x = 1,  1.5-3.0x = 2,  <1.5x = 3
Free cash flow     positive both of last two years = 0,  positive latest only = 1,
                   negative latest only = 2,  negative both = 3
EBITDA trend       change earliest->latest:  growing/flat = 0,  down <10% = 1,  down >=10% = 2
```

**Bands:** below 30% = Low Stress · 30–60% = Moderate · above 60% = Elevated.

### Why rules rather than machine learning

This was a deliberate choice, not a limitation of effort:

1. **Every point is explainable.** If the output says Elevated, I can name which
   factors contributed and which threshold each crossed. A fitted model cannot
   be defended that way.
2. **The thresholds are the finance.** 4x leverage and 3x coverage are the
   actual credit conventions, written down explicitly rather than buried in
   learned weights.
3. **Honest training data barely exists at this scale.** Corporate bankruptcies
   are rare events; a model fitted on a few hundred would learn the quirks of
   that sample rather than a general rule.

### Handling of missing data in the rating

A factor that cannot be assessed scores no points **and removes its points from
the denominator**, so the score remains a fair fraction of what was measurable.
Treating unknowns as zero would bias every poorly-disclosing company toward
"Low Stress" — exactly backwards, since weak disclosure is itself a reason for
caution. Below four assessed factors the rating is marked low-confidence.

## 7. Worked results

Verified against live Yahoo Finance data on 15 October 2026.

| Ticker | Company | Net Debt/EBITDA | Coverage | Free cash flow | Rating |
|---|---|---|---|---|---|
| AAL | American Airlines | 8.71x | 2.40x | −$680m | Elevated |
| F | Ford Motor | 39.14x | 2.73x | +$12.5bn | Elevated *(flagged)* |
| CCL | Carnival | 3.77x | 5.12x | +$2.6bn | Moderate |
| T | AT&T | 2.50x | 8.04x | +$19.4bn | Low |
| KO | Coca-Cola | 1.88x | 11.31x | +$5.3bn | Low |
| MSFT | Microsoft | 0.17x | 68.02x | +$67.0bn | Low |

Two synthetic companies (`EXMPL`, `HEALTHY`) are also bundled. They contain
invented figures, are labelled as such throughout the interface, and exist so
the tool can be demonstrated offline and so both ends of the rating scale can
be tested deterministically.

### A finding worth reporting: captive finance arms

Ford screens at **39.14x Net Debt/EBITDA**, which would be catastrophic for an
ordinary manufacturer. It is neither a calculation error nor a sign of
distress.

Ford Credit, the company's lending arm, funds a loan book, and that funding sits
as debt on Ford's balance sheet. The loan book earns **interest income**, which
is not part of EBITDA. So the numerator counts the finance debt while the
denominator ignores the finance earnings, and the ratio stops describing the
business. Banks, insurers and leasing companies behave identically.

This is the characteristic failure mode of financial software: not a crash and
not a blank cell, but **correct arithmetic producing a badly wrong
conclusion**. A missing value announces itself; a confidently printed "39.14x"
does not.

The system now flags any reading above 15x with a visible warning placed
*above* the number, explains the mechanism, and states what a real analyst does
instead — separate the industrial segment from the finance segment using the
10-K segment disclosures and compute leverage on the industrial side alone.
Four regression tests cover this behaviour.

## 8. Testing

52 unit tests, run with `python3 -m unittest discover -s tests`.

The majority test **missing and malformed data** rather than ordinary cases,
because that is where the risk lies. Specific properties under test:

- Missing inputs propagate as `None` and never become zero.
- Negative EBITDA produces no leverage multiple. `Debt / -100m` is computable
  and yields a *negative* ratio that looks healthier than a genuinely leveraged
  company; the code refuses it and explains why.
- The downside scenario refuses to run on negative EBITDA. Multiplying −120 by
  0.8 gives −96, which would display as an *improvement*.
- A 20% EBITDA decline raises leverage by exactly 25% (`1 / 0.8`).
- The Restructuring Watch never predicts default or bankruptcy.
- Unassessable rating factors shrink the denominator, not the score.

## 9. Big Data component: peer and industry comparison

**Implemented.** Every rating threshold in Section 6 is a general convention
that cannot distinguish a regulated utility from a cyclical manufacturer. An
industry median can, so the system now compares each company against the median
of its sector:

> American Airlines has Net Debt/EBITDA of **8.71x** against an Industrials
> peer median of **2.33x**, placing it in the **100th percentile** of five
> peers. Interest coverage of 2.40x compares with a peer median of 13.71x — the
> 0th percentile.

This is also where the project genuinely requires scale. One company needs seven
figures; a credible sector median needs enough peers to be meaningful, which
means fetching, caching and reconciling dozens of companies. The current data set holds **211 companies across 11 sectors**.

### Method

1. `export_web.py` runs the existing engine over the full ticker list, pausing
   between requests because Yahoo Finance rate-limits bursts.
2. Each company is grouped by the sector its data source reports.
3. For three metrics — Net Debt/EBITDA, interest coverage and EBITDA margin —
   the sector median and the company's percentile are computed by
   `screener/peers.py`.
4. Results are written to JSON and rendered by the hosted interface.

### Four statistical decisions, each defensible

**Median, not mean.** Credit ratios carry severe outliers. A single company
with near-zero EBITDA produces a reading in the hundreds, which would destroy
an average. Ford's 39.14x is exactly such a case, and the median absorbs it
without distortion.

**A company is never its own peer.** Including it would drag the benchmark
toward the very value being judged against it.

**Uncomputable values are dropped, not zeroed.** A company whose leverage is
`None` because EBITDA is negative is excluded from the median rather than
counted as zero. The number of excluded peers is displayed, because a sector
where several companies have negative EBITDA is itself a finding.

**A minimum of four peers is required.** Below that, no comparison is shown and
the interface explains why. A median built from two companies is an anecdote,
not a benchmark. Energy and Healthcare fall below this threshold in the current
set and are correctly shown without a comparison.

Synthetic teaching companies are excluded from every median, since their
figures are invented and would quietly corrupt a real benchmark.

### Limits of the current implementation

Grouping is by **broad sector** rather than narrow industry, because narrow
industry groups in a 38-company set are too small to clear the four-peer
minimum. This means an airline is compared against other industrials, including
Boeing and Caterpillar. Widening the data set to a few hundred companies would
permit true industry-level grouping, and the SEC EDGAR `companyfacts` API —
official, free, no key, standardised XBRL tags across all filers — is the right
source for that scale.

### How the live app serves this without re-fetching

The live app screens any ticker on demand, so it cannot fetch the peer group
per analysis: 36 network requests per lookup would make each analysis take
about a minute and would get the app rate-limited by Yahoo within a few uses,
especially from a shared cloud host.

Instead `build_peer_cache.py` fetches the benchmark group once and reduces it
to the few values a comparison needs — about 5 KB, committed to the repository.
The app loads it once per server process and compares against it with no
network access at all. A company that appears in the benchmark is removed from
its own peer group.

This means **any ticker can be screened and still receive a comparison**, not
only the 36 in the benchmark. Nike is not in the benchmark, yet it is compared
against the ten Consumer Cyclical companies that are.

The trade-off is that the benchmark is a snapshot while the company analysed is
live. Industry medians move slowly, so this is normal practice, and the
interface displays the benchmark date.

## 9b. SEC EDGAR as a second data source

**Implemented.** The system can now read directly from the SEC's XBRL
`companyfacts` API — the actual regulatory filings — as an alternative to
Yahoo Finance.

| | Yahoo Finance | SEC EDGAR |
|---|---|---|
| Nature | unofficial scraper | the filing itself |
| Tags | labels drift between versions | standardised XBRL across all filers |
| Key required | no | no (but a contact email is) |
| Coverage | global, including funds | US SEC filers only |

### Three problems raw filings present, and how each is handled

**Tags go stale.** Companies change which XBRL tag they use as standards
evolve. American Airlines last reported `LongTermDebtNoncurrent` in 2012 and
has used `LongTermDebt` since. Taking the first tag with any data returns a
series ending in 2012 and leaves every recent year blank — which is exactly
what the first implementation did. Candidate tags are therefore *merged by
period*: each year takes its value from the highest-preference tag that
actually covers that year.

**Every filing restates the prior year.** The same fiscal year appears in
several 10-Ks, so the most recently *filed* value is kept, which reflects any
restatement.

**Quarters and years share a tag.** Income-statement facts carry both,
distinguished only by period length. Counting a quarter as a year would
understate revenue roughly fourfold. Periods of 330–400 days count as annual,
a range wide enough for the 52- and 53-week fiscal years retailers use.

### Coverage, measured

Tested across the 34 benchmark companies:

| | |
|---|---|
| Complete | 30 |
| Partial | 3 |
| Unparseable | 1 |

Reaching 30 required widening the tag lists after seeing real output. Delta
tags neither `InterestExpense` nor `InterestExpenseNonoperating`, so coverage
was blank until net and cash-paid variants were added. Verizon's capex sits
under `PaymentsToAcquireOtherProductiveAssets` alone. IBM and Pfizer never tag
`OperatingIncomeLoss` at all, so EBIT is rebuilt from pre-tax income plus
interest expense — the definition of EBIT read backwards.

The four remaining gaps are honest data absences rather than defects, and each
is reported as unavailable rather than guessed:

- **Ford and GM** give no total debt. Both tag captive-finance borrowing in
  company-specific extension namespaces outside `us-gaap`. This is the same
  underlying problem as the 39x reading in Section 7, seen from another angle.
- **Apple** gives no interest expense, netting it against interest income.
- **Exxon** cannot be parsed at all; the error directs the reader to Yahoo.

This is the honest cost of using raw filings: filers have real latitude in
which tags they use, and no fixed list covers every company. The alternative —
guessing at a figure when the expected tag is absent — would be worse.

### A finding: the two sources disagree about total debt

For American Airlines' 2025 fiscal year:

| Source | Total debt |
|---|---|
| Yahoo Finance | 36,884m |
| SEC EDGAR | 29,007m |

Neither is wrong. The ~7,900m gap is **operating lease liabilities**, which
Yahoo includes in total debt and this EDGAR implementation does not. Finance
leases are included in both, because they are fixed contractual obligations
indistinguishable from borrowing.

This matters because it changes the output: American Airlines screens
**Elevated** on Yahoo data and **Moderate** on EDGAR data. The arithmetic is
identical; the input definition differs.

The wider lesson is that "total debt" is a choice rather than a fact, and a
credit screen is only as consistent as its definition. A real analyst states
which definition they are using. The application names its source on every
report for this reason.

### A second finding: captive finance arms resist standard tags

Ford returns no leverage figure at all from EDGAR. Its debt sits in
company-specific extension tags that split automotive from Ford Credit
borrowing, rather than in the standard `us-gaap` ones. The tool correctly
reports this as unavailable instead of guessing — and it is the same company
that produces the misleading 39x reading discussed in Section 7. The two
findings are the same underlying problem seen from different angles.

## 9c. A published second opinion: the Altman Z''-score

The five-factor rating in Section 6 is this project's own invention. Its
thresholds are defensible credit conventions, but nothing validates them
against real outcomes. The Altman Z-score has been in use since 1968, is
taught in every corporate finance course, and was fitted against companies
that actually did and did not fail. Running both and showing them side by side
is more honest than either alone.

    Z'' = 6.56(WC/TA) + 3.26(RE/TA) + 6.72(EBIT/TA) + 1.05(Equity/TL)

The coefficients are Altman's published values. Nothing is fitted here — that
is the point of using an outside model. The Z'' variant is used because it
drops the original formula's sales-to-assets term and uses book rather than
market equity, which makes it valid across industries and removes any need for
share-price data.

### The two measure different things

| | Our rating | Altman Z'' |
|---|---|---|
| Question | Can it keep paying what it owes? | Has it accumulated enough value to absorb losses? |
| Reads | leverage, coverage, cash flow, earnings | working capital, retained earnings, asset productivity, equity |
| Nature | **debt service** | **balance sheet** |

Agreement is reassurance. Disagreement is information, not error.

### Results

| Ticker | Our rating | Z'' | Altman zone | |
|---|---|---|---|---|
| AAL | Elevated | −1.54 | Distress | agree |
| CCL | Moderate | 0.09 | Distress | agree |
| KO | Low | 4.55 | Safe | agree |
| MSFT | Low | 4.59 | Safe | agree |
| NKE | Moderate | 3.37 | Safe | **disagree** |
| KSS | Low | 1.58 | Grey | **disagree** |

The disagreements are the interesting cases. **Nike** is flagged Moderate by
our rating because EBITDA fell 32% and interest expense was unavailable, but
Altman sees a strong balance sheet with healthy working capital and large
retained earnings. Both are right about what they measure: earnings are
deteriorating while the balance sheet remains well capitalised. A company in
that position has time to fix the earnings problem, which is precisely what
our debt-service view cannot see.

### Availability

The Z-score needs the full balance sheet, which both live sources supply. The
two synthetic teaching companies were extended with internally consistent
balance sheets so the score can be demonstrated with no internet connection:
EXMPL walks from the grey zone (2.33) into distress (−0.58) across the five
years, while HEALTHY stays safe throughout.

### Deliberate exclusions

Banks and insurers are refused rather than scored. Altman's model was never
fitted on financial institutions, whose balance sheets work differently enough
that the ratios lose their meaning — deposits are liabilities in a sense that
has nothing to do with solvency risk, and working capital is not a meaningful
concept for them. A test enforces this.

A second test asserts that `rating.py` never imports the Z-score. If the main
rating consulted it, "two independent methods agree" would be circular.

## 9d. Three visuals that carry analysis rather than decorate

**The rating trajectory.** The rating recomputed as of every past year, drawn
over the same bands it scores against. A single rating says where a company
stands; this says *when it got there*, which is often the more useful fact.
Each point uses a truncated history — the 2023 point sees 2023 and nothing
after — so it is a genuine point-in-time rating rather than hindsight applied
backwards. EXMPL walks visibly from low stress in 2022 into elevated in 2024.

**Threshold bands on the leverage chart.** The background is shaded into the
conventional credit bands (under 2x, 2–4x, 4–6x, above 6x). The line crossing
into red *is* the rating logic, shown rather than described, so a reader
understands the verdict without being walked through a table.

**The debt maturity wall.** Principal due by year, with cash drawn across it
as a dashed line. This answers the question Section 10 names first and
leverage structurally cannot: companies fail when they miss a payment on a
date, not when a ratio crosses a threshold.

For American Airlines the picture is immediate: **3.6bn falls due within
twelve months against 1.1bn of cash.** The shortfall must come from operating
cash flow, asset sales or refinancing — and *whether refinancing is available,
and at what cost* is now a question the tool raises with numbers attached
rather than as generic advice.

Maturities come only from SEC EDGAR, since they live in the long-term debt
note of the 10-K. Rungs a filer did not tag are left out rather than shown as
zero, and the interface says which.

## 9e. Industry watch: live restructuring activity

The tool now carries a live feed of restructuring events, read from SEC
filings rather than news coverage.

**Why filings rather than headlines.** A news feed would mean scraping a
publisher's site: fragile, usually behind a paid key, and offering a
journalist's summary of an event rather than the event. The SEC's full-text
search covers every filing by every US public company, is free, requires no
key, and returns the primary document. It is also the same source the screener
already reads, so the project has one view of the world rather than two.

**Five watched event types**, each keyed to an exact phrase, because filings
are legal documents whose language is stable in a way headlines are not:

| Event | What it means |
|---|---|
| Chapter 11 petitions | The outcome the whole screen tries to anticipate |
| Restructuring support agreements | Creditor deal struck, often days before a filing |
| Going-concern doubt | The strongest formal warning in financial reporting |
| Forbearance and covenant waivers | A breach being negotiated — the covenant headroom the screener cannot see |
| Debtor-in-possession financing | New money ranking ahead of existing debt; a private-credit specialism |

Each item links to the filing itself, so a reader can check the claim rather
than take it on trust. A single event often produces several near-identical
hits, because EDGAR indexes each document in a filing separately; results are
de-duplicated by accession number so one 8-K appears once.

**It closes the loop with the screener.** Companies appearing in the feed can
be screened directly in the Company tab, so a reader can ask what the tool
would have said before the event. Note that companies in Chapter 11 trade
under a Q-suffixed symbol the data sources no longer carry, so the plain
ticker is offered where one exists.

### The briefing: a counted summary rather than a written one

The obvious way to summarise an industry is to hand a pile of headlines to a
language model and ask for a paragraph. That produces something readable,
unverifiable, and different on every run.

The briefing does the opposite. It counts: distress filings this window
against the previous one, which 8-K items were triggered, which industries
they came from, which terms recur across the press. The prose is then
assembled from those counts, so every sentence traces to a number displayed
beside it.

A recent run, over sixty days against the prior sixty:

| | |
|---|---|
| Distress filings | **240**, up 19% from 202 |
| Item 1.03 (bankruptcy or receivership) | 23 |
| Item 2.04 (debt acceleration) | 9 |
| Largest category | Debtor-in-possession financing, 84 |
| Clustering in | Services, pharmaceuticals, banking |

**The 8-K item numbers are the strongest signal in the whole feed.** Companies
file 8-Ks under items the SEC prescribes rather than chooses. Item 1.03 is
"Bankruptcy or Receivership" — a filing carrying it has entered an insolvency
process. That is harder than any phrase search, because a company cannot
trigger it by merely discussing bankruptcy in passing. Item 2.04 covers debt
acceleration, which is typically what follows a covenant breach, and is the
earliest formal sign that lenders have acted.

Industry grouping uses SIC major groups, the classification each filer
registered under.

**The briefing always states its own caveat**, enforced by a test: these are
counts of formal filings, not a judgement about the market. A rise can reflect
genuine deterioration or simply the reporting calendar, since many industries
cluster their fiscal year-ends and filings follow.

### Press coverage alongside filings

The tab carries a second view: syndicated headlines from thirteen publishers'
public RSS feeds, filtered to credit and restructuring. The two complement
each other — filings are narrow and checkable, while journalism covers
negotiation and sector pressure weeks before anything reaches a filing, and
covers private credit, which barely files at all.

**A subscription is not API access.** A personal WSJ or NYT subscription lets
a person read articles in a browser; it grants an application nothing. What
these publishers do offer is public RSS: headlines, summaries and links, free
and keyless. The reader clicks through and their own subscription handles the
paywall. Nothing here circumvents one.

**A bug worth recording.** The relevance filter originally matched keywords as
plain substrings, which looked correct and was quietly wrong: `lbo` matched
*Dea**lbo**ok*, `clo` matched *neo**clo**ud*, and personal-finance advice
columns matched on `debt`. Matching is now on word boundaries, with two tiers —
one unambiguous term qualifies an article, while common terms like "debt" need
a second one — plus an exclusion list for advice columns. Nine test cases, each
a real headline the first version misclassified.

**What it is not.** The filings half is formal disclosure, not journalism: it
reports what has been filed, not what is rumoured. The press half is the
reverse. Neither alone is the whole picture, which is why both are shown.

## 9f. Learn: a quiz on the concepts the tool uses

A screening tool is only useful to someone who understands what it reports, so
the application carries a quiz on private credit and restructuring
fundamentals.

Fifteen questions across four topics — metrics, restructuring, private credit
and analysis — at three levels. Every question ties to something the tool
itself computes or displays, so studying the quiz and reading a screen
reinforce each other. The Ford question asks why a 39x reading is not
distress; the stress-test question asks why a 20% earnings fall raises
leverage 25%.

**The explanations carry the teaching, not the scoring.** Each wrong option
has its own reason attached, because in credit the plausible-but-wrong answer
is usually the more instructive one. Answering "a 20% EBITDA fall raises
leverage 20%" is worth more as a lesson than simply being marked wrong: the
arithmetic is 1 ÷ 0.8, and that asymmetry is the whole reason leverage creates
fragility.

Twelve tests check the bank structurally — every answer index valid, every
wrong option explained, no explanation attached to a correct answer, no
repeats within a round, and a fixed seed so a Streamlit rerun does not
reshuffle a round in progress. A quiz that marks a correct answer wrong
teaches the opposite of what it intends.

## 10. Limitations

Knowing what the tool cannot do is most of understanding it.

1. **Debt maturities are available only from SEC EDGAR**, and only where the
   filer tagged them. On the Yahoo source the tool remains blind to timing.
   This was the project's largest gap and is now partly closed (Section 9d).
2. **No covenant information.** A breach can allow lenders to demand immediate
   repayment, which is frequently what actually starts a restructuring.
3. **Industry context is broad.** Peer comparison groups by sector rather
   than narrow industry (Section 9), and covers 38 companies rather than a full
   market.
4. **No assessment of EBITDA quality.** Reported figures may include generous
   add-backs, and every ratio rests on that denominator.
5. **No liquidity picture.** Undrawn revolving credit facilities do not appear
   in the seven collected figures and can be the difference between a problem
   and a crisis.
6. **Cannot distinguish cyclical from structural decline.** The judgement that
   matters most, which no ratio answers.
7. **Annual data only.** A company can deteriorate quickly inside a fiscal
   year.
8. **Captive finance arms distort leverage.** Mitigated by the warning
   described in Section 7, not solved.
9. **EDGAR covers only SEC filers**, and returns no sector classification, so
   peer comparison is unavailable on that source. Foreign issuers reporting
   under IFRS, funds and private companies are absent.
10. **Yahoo Finance is an unofficial source.** It is a scraper, occasionally
   omits line items, and can change without notice. Where EBITDA is not
   reported, the loader reconstructs it as Operating Income + D&A and records a
   note that is displayed in the output. That is a disclosed reconstruction
   from reported figures, not an invention.

## 11. How to run it

### Deployed

The application is live and needs no installation:

**https://restructuring-watch.streamlit.app**

It runs the same Python engine against Yahoo Finance on demand, so any public
ticker can be screened. A light/dark toggle sits at the top of the sidebar.

### Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

A browser opens; enter a ticker and press **Analyze Company**.

Command-line version (no dependencies beyond the standard library):

```bash
python3 main.py --ticker AAL --source yfinance
```

Offline demonstration, no internet required:

```bash
python3 main.py --ticker EXMPL
```

Tests:

```bash
python3 -m unittest discover -s tests -v
```

## 12. File inventory

| Path | Purpose |
|---|---|
| `app.py` | Streamlit web dashboard |
| `main.py` | Command-line interface |
| `screener/models.py` | Shared data structures |
| `screener/data_loader.py` | Stage 1 — Yahoo Finance, SEC EDGAR and local JSON |
| `screener/edgar.py` | The SEC XBRL client and tag extraction |
| `screener/metrics.py` | The six credit formulas |
| `screener/signals.py` | The seven warning signals |
| `screener/scenario.py` | Downside stress test |
| `screener/rating.py` | Five-factor stress rating |
| `screener/narrative.py` | Plain-language explanation layer |
| `screener/ai.py` | Optional Claude rewording layer |
| `screener/report.py` | Plain-text report |
| `screener/peers.py` | Median and percentile calculations (Section 9) |
| `screener/altman.py` | The published Altman Z''-score (Section 9c) |
| `build_web.py` | Injects exported data into the hosted page template |
| `build_peer_cache.py` | Builds the sector benchmark the live app uses |
| `data/peer_cache.json` | The committed benchmark (211 companies, 7 sectors) |
| `tests/test_metrics.py` | 52 unit tests |
| `data/*.json` | Synthetic teaching companies |
| `web/index.html` | Static hosted version |
| `export_web.py` | Exports computed results for the hosted version |

Approximately 4,900 lines including comments and tests.

## 13. Next steps

1. Build the peer benchmark from EDGAR rather than Yahoo, and widen the set to a few hundred companies so grouping can move from broad
   sector to narrow industry.
3. Add debt maturity data if a free source can be identified, since this is the
   single largest analytical gap.
3. Extend the stress test to allow a revenue decline as well as an EBITDA
   decline.

---

*This tool is for educational and analytical purposes and is not investment or
lending advice. It does not predict default or bankruptcy.*
