# Credit Health & Restructuring Watch Agent

A first-pass screening tool that answers one question about a public company:

> **Is this company's credit profile improving or deteriorating, and are there
> warning signs that could eventually require restructuring analysis?**

**Live app: https://restructuring-watch.streamlit.app** — no installation, any
public ticker.

It is deliberately **not** a bankruptcy predictor and **not** a restructuring
adviser. It flags warning signs for a human analyst to investigate, the way a
screen is used in practice: to sort a long list of companies into "look
harder" and "move on".

---

## Quick start

### The web dashboard (what you'll demo)

```bash
pip install -r requirements.txt
streamlit run app.py
```

A browser opens at `http://localhost:8501`. Type a ticker, press **Analyze
Company**, and the agent runs its workflow in front of you.

Two synthetic teaching companies are bundled and work with no internet at all —
switch the sidebar to **Local file (offline)** and enter:

- **EXMPL** — a steadily deteriorating credit (screens *Elevated*)
- **HEALTHY** — a sound one (screens *Low*)

Both are invented figures, clearly labelled in the app, and describe no real
company. For real tickers leave the sidebar on **Yahoo Finance (live)** and
enter something like `AAL` or `F`.

### The command-line version

The same engine, no dependencies at all:

```bash
python3 main.py --ticker EXMPL
```

```bash
python3 main.py --ticker AAL --source yfinance --save report.txt
```

### The tests

```bash
python3 -m unittest discover -s tests -v
```

### Using SEC EDGAR instead of Yahoo

EDGAR serves the actual regulatory filings rather than a scraped copy. It is
free and needs no API key, but the SEC requires every automated request to
identify its sender and refuses anonymous ones:

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
```

On Streamlit Community Cloud that goes in the app's **Secrets** panel instead.
Use a real address you monitor — that is the condition of access.

**The EDGAR option only appears in the sidebar once this is set.** An
interface that offers a choice which cannot work is worse than one that offers
fewer choices, so the option is hidden rather than shown with an error.

Then pick **SEC EDGAR (official)** in the sidebar, or from the command line:

```bash
python3 main.py --ticker AAL --source edgar
```

**Expect some figures to differ from Yahoo's.** This is not a bug in either
source; see the note on total debt in the project report.

### Refreshing the industry benchmark

The app compares each company against its sector median, using a benchmark
committed at `data/peer_cache.json`. To rebuild it from current data:

```bash
python3 build_peer_cache.py
```

That fetches ~36 companies once and writes about 5 KB. The app reads it with no
network access, so any ticker can be screened and still get a comparison.

---

## Putting it online so your professor can open a URL

Streamlit Community Cloud hosts this free. You need a GitHub account.

**1. Put the project on GitHub.**

```bash
git init && git add . && git commit -m "Financial distress screening agent"
```

Create an empty repository on github.com, then follow the two `git remote add`
/ `git push` lines it shows you.

**2. Deploy.** Go to [share.streamlit.io](https://share.streamlit.io), sign in
with GitHub, click **New app**, and point it at your repository with
`app.py` as the main file. It installs `requirements.txt` automatically and
gives you a URL like `https://yourname-distress-screener.streamlit.app`.

**3. (Optional) Add the Claude key.** In the app's **Settings → Secrets**, add:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

Leave this out and the app runs in template mode — fully functional, and it
says so in the sidebar.

**Never commit an API key to GitHub.** Secrets go in the Streamlit settings
panel, never in a file you push.

---

## The design principle

**Python does all the arithmetic. The AI only explains it.**

Every number in the report comes from a pure function in `screener/metrics.py`
that you can unit-test. The AI layer, if you add one, rewords the prose — it
never touches a figure.

This matters for three reasons you should be able to state out loud:

1. **Reproducibility.** Every number is identical on every run, including
   with Claude enabled — because Claude never produces a number. That is not
   true of a project where a language model does the maths.
2. **Auditability.** Every figure traces back to a named function and a
   reported line item, and every stress point to a written threshold.
3. **It still works with the AI switched off.** The default mode uses no
   language model at all. The AI is a presentation layer, not a dependency.
4. **The UI is replaceable.** The command-line tool and the web dashboard call
   the same functions and produce the same figures, so the finance can be
   tested without a browser and the browser rebuilt without risking the
   finance.

### The rule about missing data

**A number we could not obtain is `None`. It is never zero, and it is never
estimated.**

Zero and unknown mean completely different things in credit analysis. Zero
debt is excellent news; unknown debt means you cannot form a view at all. The
code propagates `None` through every calculation and the report prints `n/a`
with a stated reason. A screening tool that silently invents inputs produces
confident nonsense, which is worse than producing nothing.

---

## Architecture

Four stages, each in its own file, each independently testable. Two front ends
share all of it.

```
    TICKER
      │
      ▼
┌─────────────────┐   STAGE 1: GET THE DATA
│  data_loader.py │   Fetch ~5 years of 7 raw numbers from local JSON
└─────────────────┘   or yfinance. Missing → None, never guessed.
      │
      ▼  FinancialHistory
┌─────────────────┐   STAGE 2: DO THE MATH  (pure Python, no AI)
│   metrics.py    │   The six ratios, per year
│   signals.py    │   Compare years → which warning signs fired?
│   scenario.py   │   Re-run the math with EBITDA cut 20%
│   rating.py     │   Five scored factors → Low / Moderate / Elevated
└─────────────────┘
      │
      ▼
┌─────────────────┐   STAGE 3: EXPLAIN IT
│  narrative.py   │   Prose assembled from the computed facts (always)
│     ai.py       │   OPTIONAL: Claude rewords it (never recalculates)
└─────────────────┘
      │
      ├────────────────────┬──────────────────────
      ▼                    ▼
┌─────────────┐     ┌─────────────┐
│  report.py  │     │   app.py    │   STAGE 4: SHOW IT
│   (text)    │     │ (dashboard) │   Formatting only. No arithmetic.
└─────────────┘     └─────────────┘
      │                    │
      ▼                    ▼
   main.py            streamlit run
```

The CLI and the dashboard produce identical numbers because they call the same
pure functions. That is the point of the boundary: you can rebuild the whole UI
without endangering the finance, and unit-test the finance without touching the
UI.

### File structure

```
credit-health-agent/
├── README.md                 this file
├── PROJECT_REPORT_DRAFT.md   the written project report
├── requirements.txt          streamlit + yfinance (anthropic optional)
│
├── app.py                    THE WEB DASHBOARD — streamlit run app.py
├── main.py                   the command-line version
│
├── screener/
│   ├── models.py             FiscalYear, FinancialHistory — shared shapes
│   ├── data_loader.py        Stage 1: yfinance + local JSON
│   ├── metrics.py            the six formulas, one function each
│   ├── signals.py            the seven credit signals
│   ├── scenario.py           the EBITDA downside stress test
│   ├── rating.py             the transparent five-factor score
│   ├── peers.py              sector medians and percentiles
│   ├── narrative.py          Stage 3: prose built from computed facts
│   ├── ai.py                 Stage 3 (optional): Claude rewording layer
│   └── report.py             Stage 4: the plain-text report
│
├── data/
│   ├── EXMPL.json            synthetic deteriorating company
│   ├── HEALTHY.json          synthetic sound company
│   └── peer_cache.json       the sector benchmark (36 companies, 7 sectors)
│
├── tests/test_metrics.py     59 unit tests
│
├── build_peer_cache.py       rebuilds the sector benchmark
├── export_web.py             runs the engine over the hosted company set
├── build_web.py              injects that data into the hosted page
├── make_favicon.py           regenerates the browser-tab icon
├── assets/favicon.png        the icon itself
└── web/template.html         the hosted page (data injected at build time)
```

---

## What the website shows

Ten sections, in the order an analyst would read them:

| # | Section | What it does |
|---|---|---|
| 1 | **Ticker input** | One field, one button |
| 2 | **Agent workflow** | Each step shown as it runs, so the pipeline is visible |
| 3 | **Key metrics** | Four large cards, each with a (?) tooltip definition |
| 4 | **Stress rating** | Low / Moderate / Elevated, with *Why?* bullets — never a bare score |
| 5 | **Historical trends** | Three charts: leverage, coverage, free cash flow |
| 6 | **What is happening?** | Plain-language explanation, plus *Why this matters* |
| 7 | **Warning signs** | 🔴 🟠 🟢 ⚪ per signal, each expandable for the reasoning |
| 8 | **Downside scenario** | A **slider** — drag it and watch leverage rise faster than earnings fall |
| 9 | **Analyst questions** | What to investigate next, and why each one matters |
| 10 | **Sources & limitations** | Where the data came from and what the tool cannot see |

Three deliberate choices in the UI worth being able to defend:

- **A rating is never shown without its reasons.** "72/100" tells a reader
  nothing. Every stress point traces to one stated threshold, shown on screen.
- **Charts use a zero-based y-axis.** A truncated axis makes a small change
  look dramatic. On a zero-based axis a move from 2x to 6x looks large and a
  move from 8.7x to 9.7x looks modest — which is the truth in both cases.
- **Negative free cash flow bars are red, positive are green.** A loss-making
  year drawn in green reads as good news at a glance, which is backwards.
- **A correct number that means the wrong thing gets a red warning.** A blank
  cell announces itself; a confidently-printed "39.14x" does not. Where a
  ratio is arithmetically right but the wrong lens for that business model
  (see limitation 9), the app says so above the number, not in a footnote.

### The explanation layer: two modes

This distinction matters, and you should state it precisely rather than calling
the whole thing "AI".

| | **Template mode** (default) | **Claude mode** (optional) |
|---|---|---|
| How the prose is made | Python picks from sentences a human wrote | Claude rewords the computed facts |
| Needs an API key | No | Yes |
| Deterministic | Yes — same input, same words | No |
| Cost | Free | A fraction of a cent per company |
| Does the maths | **No** | **No** |
| Decides the rating | **No** | **No** |

**The project runs in template mode.** Explanations are written by Python, so
the wording is identical on every run — part of the reproducibility claim
rather than a limitation of it. The Claude layer is optional, off, and the
only part of the project that would cost anything.

**In both modes Python does every calculation and decides the rating.** The
language model, when enabled, receives only the already-computed figures and is
instructed to introduce no numbers of its own. It changes the wording, never
the numbers. The app says which mode produced the text you are reading.

To enable Claude:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Then tick **Use Claude for explanations** in the sidebar. Without a key the
toggle is disabled and the sidebar explains why.

---

## The finance, explained

This section is the study guide. Read it alongside the code comments, which go
into more depth on each point.

### EBITDA

**E**arnings **B**efore **I**nterest, **T**axes, **D**epreciation and
**A**mortization.

Start from net income and add back four things:

| Added back | Why |
|---|---|
| **Interest** | Depends on how the company chose to finance itself, not on how the business performs |
| **Taxes** | Depends on jurisdiction and tax history |
| **Depreciation** | An accounting charge spreading an old purchase over years — no cash leaves this year |
| **Amortization** | The same idea for intangible assets |

What remains approximates **cash the core business generates before financing
decisions**. Credit analysts use it because it lets you compare two companies'
operations without their debt structures getting in the way.

**Its famous weakness:** EBITDA ignores capital expenditure. A company that
must constantly replace equipment looks better on EBITDA than it really is.
Charlie Munger was blunt about this, and he had a point. That weakness is
exactly why this tool also computes free cash flow — the two together are
honest in a way either is not alone.

### Leverage

How much debt a company carries **relative to its ability to service it**.

Not the dollar amount. $5bn of debt is trivial for Apple and fatal for a
mid-size retailer. Leverage is always a ratio, which is why every metric below
divides by something.

### The six metrics

| Metric | Formula | Plain meaning |
|---|---|---|
| **Debt / EBITDA** | `Total Debt ÷ EBITDA` | Years of EBITDA to repay all debt |
| **Net Debt / EBITDA** | `(Total Debt − Cash) ÷ EBITDA` | Same, crediting cash already held |
| **Interest Coverage** | `EBITDA ÷ Interest Expense` | Times over the interest bill is covered |
| **Free Cash Flow** | `Operating Cash Flow − Capex` | Cash genuinely left over |
| **EBITDA Margin** | `EBITDA ÷ Revenue` | Operating earnings per dollar of sales |
| **Revenue Growth** | `(Rev_t ÷ Rev_t−1) − 1` | Year-over-year change in the top line |

#### Debt / EBITDA

Read it as: *"how many years of EBITDA would it take to repay all the debt?"*

Rough market convention:

| Level | Reading |
|---|---|
| under 2.0x | conservative |
| 2.0 – 4.0x | normal for a leveraged but healthy business |
| 4.0 – 6.0x | genuinely leveraged; lenders are paying attention |
| over 6.0x | stressed; refinancing becomes difficult and expensive |

These are conventions, not laws, and they vary enormously by industry. A
regulated utility with contracted cash flows can carry 5x comfortably; a
cyclical miner at 5x is in trouble. **This is the single biggest limitation of
the current tool**, and what `peers.py` is designed to fix.

#### Net Debt / EBITDA

The same question, giving the company credit for cash it already holds. Always
lower than or equal to Debt/EBITDA. Generally the more realistic measure, and
credit agreements are often written against it.

**Watch the gap between the two.** A large gap means much of the apparent
leverage is offset by cash — but ask whether that cash is genuinely available.
Cash trapped in a foreign subsidiary, or needed for day-to-day operations,
cannot actually repay debt.

#### Interest Coverage

Read it as: *"how many times over can the company pay this year's interest out
of this year's operating earnings?"*

| Level | Reading |
|---|---|
| over 6.0x | comfortable |
| 3.0 – 6.0x | adequate |
| 1.5 – 3.0x | tight; little room for a bad year |
| under 1.5x | the company can barely afford its own debt |

**This is the most urgent metric of the six.** Leverage measures *size*;
coverage measures *timing*. High leverage is survivable for years if coverage
is comfortable. But interest payments are due on fixed dates, and missing one
is an **event of default** — which can accelerate the entire loan and force a
restructuring immediately. When coverage approaches 1.0x, the problem stops
being theoretical.

#### Free Cash Flow

The number that cuts through accounting. EBITDA deliberately ignores the cost
of maintaining the asset base; FCF does not.

**Why it matters most under stress:** FCF answers *"is this situation stable,
or deteriorating on its own?"*

- **Positive FCF** → the company services its debt and slowly repays it.
- **Negative FCF** → the company must find cash elsewhere *every year*: draw
  down reserves, sell assets, or borrow more. If it borrows, debt rises while
  the earnings that service it do not, so **leverage increases mechanically,
  year after year, with no single dramatic event.**

That slow spiral — negative FCF funded by rising debt — is the most common
path into financial distress. It is exactly the pattern the `EXMPL` sample
data demonstrates.

#### EBITDA Margin

Useful for separating a **volume** problem from a **profitability** problem. If
revenue is flat but margin is falling, the company is selling just as much and
keeping less of it: costs rising faster than prices, or discounting to defend
share. Both usually show up *before* the leverage ratios react.

#### Revenue Growth

Matters first because it is the input to everything else. Falling revenue flows
into falling EBITDA, which raises leverage and lowers coverage. **A company can
become more leveraged while borrowing nothing at all, purely by shrinking.**

---

## The seven stress signals

Each is one simple question comparing the earliest year with the latest:

1. Revenue falling
2. EBITDA falling
3. Debt increasing
4. Debt / EBITDA increasing
5. Interest coverage decreasing
6. Negative free cash flow
7. Cash decreasing

Each returns **fired**, **clear**, or **unknown** — and `unknown` is never
reported as `clear`, because "we didn't check" is not "no problem".

### The interpretive rule

**No single signal means a company is in trouble.** Every one has an innocent
explanation as well as a worrying one:

| Signal | Innocent reading | Worrying reading |
|---|---|---|
| Debt rising | funding a profitable acquisition | funding an operating shortfall |
| Negative FCF | a deliberate expansion programme | the business cannot fund itself |
| Revenue falling | exiting a low-margin business on purpose | losing customers |
| Cash falling | a buyback from a position of strength | cash consumed by losses |

What matters is **how many fire together and whether they tell one coherent
story**. Three signals pointing the same way is a pattern worth investigating.
One signal alone is a question, not an answer.

---

## The downside scenario

One question: **what happens if EBITDA falls 20%?**

Debt, cash and interest expense are held constant; the three ratios that
depend on EBITDA are recomputed.

### The arithmetic that makes leverage dangerous

A 20% fall in EBITDA raises the leverage ratios by **25%**, not 20%:

```
1 ÷ 0.8 = 1.25
```

The numerator (debt) did not change. Only the denominator shrank. Dividing by
a smaller number moves the ratio more than the input moved. Interest coverage
falls by the same 25% proportion.

Worked example from `EXMPL`:

| | Base | EBITDA −20% |
|---|---|---|
| EBITDA | 300 | 240 |
| Debt / EBITDA | 6.50x | **8.12x** |
| Net Debt / EBITDA | 5.88x | **7.35x** |
| Interest coverage | 2.22x | **1.78x** |

**This asymmetry is the whole reason leverage creates fragility.** An unlevered
company that loses a fifth of its earnings has a disappointing year. A company
at 5x leverage that loses a fifth of its earnings is at 6.25x and may have
breached a covenant.

### What the scenario deliberately does not do

- It does not move working capital, capex or borrowing. Holding everything
  else constant **isolates the single effect of lower earnings**, which makes
  the result easy to interpret. It is a sensitivity test, not a forecast.
- It does not recompute free cash flow, because this scenario makes no
  assumption about how a 20% EBITDA decline translates into operating cash
  flow. Guessing at that link would be inventing data.
- **It refuses to run when EBITDA is negative.** Multiplying −120 by 0.8 gives
  −96, which would appear as an *improvement*. Rather than pick a convention,
  the tool declines and explains that for a loss-making company the live
  question is liquidity, not a further earnings decline.

---

## The stress rating

Five factors, each scored against published thresholds. Points are summed and
divided by the maximum that could actually be assessed.

| Factor | Max | What it captures |
|---|---|---|
| Leverage level | 3 | the **size** of the problem |
| Leverage trend | 2 | the **direction** — often more telling than the level |
| Interest coverage | 3 | the **urgency**; this is what forces a default |
| Free cash flow | 3 | whether the situation is **self-correcting or worsening** |
| EBITDA trend | 2 | the **engine** driving all four of the above |

Together: *how bad, getting better or worse, how urgent, self-funding, and
why.*

### The thresholds

```
Leverage level     Net Debt/EBITDA:  <2.0x = 0,  2.0–4.0x = 1,  4.0–6.0x = 2,  >6.0x = 3
Leverage trend     Change earliest→latest:  improving/flat = 0,  worse <1.0x = 1,  worse ≥1.0x = 2
Interest coverage  EBITDA/interest:  >6.0x = 0,  3.0–6.0x = 1,  1.5–3.0x = 2,  <1.5x = 3
Free cash flow     Positive both of last two years = 0,  positive latest only = 1,
                   negative latest only = 2,  negative both = 3
EBITDA trend       Change earliest→latest:  growing/flat = 0,  down <10% = 1,  down ≥10% = 2
```

### The bands

| Score ÷ assessable max | Rating |
|---|---|
| below 30% | **Low Stress** |
| 30% – 60% | **Moderate Stress** |
| above 60% | **Elevated Stress** |

### Why rules and not machine learning

1. **Every point is explainable.** If the output says "Elevated", you can name
   which factors contributed and what threshold each crossed. A
   gradient-boosted model cannot be defended that way in a meeting.
2. **The thresholds *are* the finance.** 4x leverage, 3x coverage — these are
   the credit conventions, written down explicitly rather than buried in
   fitted weights.
3. **Honest training data barely exists at this scale.** Corporate
   bankruptcies are rare, so a model fitted on a few hundred learns the quirks
   of that sample. A transparent rule set does not pretend to a precision it
   does not have.

### How missing data is handled

A factor that cannot be assessed scores **no points and removes its points
from the maximum**, so the score stays a fair fraction of what was measurable.

Treating unknowns as zero would quietly bias every under-reported company
towards "Low Stress" — exactly backwards, since poor disclosure is itself a
reason for caution. Below four assessed factors the rating is marked
**LOW CONFIDENCE**.

One exception, which is a deliberate judgement: a company with **negative
EBITDA** cannot have its leverage expressed as a multiple, but it must not slip
through as "unassessed". It takes maximum points on both leverage and coverage,
because no multiple of negative earnings can repay debt.

---

## Data sources

### Local JSON (default, no dependencies)

Copy `data/EXMPL.json` and type figures from a company's 10-K. This works
offline, which matters for a demo, and typing numbers out of a real filing once
is the fastest way to learn where these line items actually live.

```json
{
  "ticker": "XYZ",
  "company_name": "Example Corp",
  "currency": "USD",
  "units": "millions",
  "source_note": "Figures typed from the FY2025 10-K, filed 2026-02-14.",
  "fiscal_years": [
    {
      "year": 2025,
      "revenue": 3850,
      "ebitda": 300,
      "cash": 185,
      "total_debt": 1950,
      "interest_expense": 135,
      "operating_cash_flow": 150,
      "capex": 225
    }
  ]
}
```

Use `null` for a figure you genuinely cannot find. Do **not** use `0`.

**Sign conventions** (the loader normalises these, but know them):
- `interest_expense` — positive, meaning money paid out
- `capex` — positive, meaning money spent

Most data sources report both as negative. Storing them positive makes
`FCF = OCF − capex` read like the textbook formula.

**Where to find each number in a 10-K:**

| Field | Statement | Typical label |
|---|---|---|
| Revenue | Income statement | Total revenue / Net sales |
| EBITDA | *usually not reported* — compute as Operating income + D&A | |
| Cash | Balance sheet | Cash and cash equivalents |
| Total debt | Balance sheet | Short-term debt + Long-term debt |
| Interest expense | Income statement | Interest expense, net |
| Operating cash flow | Cash flow statement | Net cash from operating activities |
| Capex | Cash flow statement | Purchases of property and equipment |

### yfinance (optional)

Free, no API key, no sign-up. Two honest caveats to be able to state:

- **It is an unofficial scraper.** It breaks when Yahoo changes its pages, and
  row labels drift between versions. The loader tries several known labels per
  field and leaves the field `None` if none match.
- **Yahoo sometimes omits EBITDA.** When it does, the loader rebuilds it as
  `Operating Income + D&A` and **records a note that appears in the report**.
  That is a disclosed reconstruction from reported figures, not an invention.

### SEC EDGAR (the planned upgrade — not built)

`companyfacts` is official, free, needs no key, covers every US filer, and uses
standardised XBRL tags. It is the right backbone for the Big Data phase. Add it
as a third `_load_*()` function in `data_loader.py`; nothing else changes.

---

## The Big Data extension (planned, not built)

The goal:

> "Company A has Net Debt/EBITDA of 4.5x compared with an industry median of
> 2.8x, placing it in the 85th percentile of its sector."

**Why this is the right next step.** Every threshold in `rating.py` is a
general convention that cannot know the difference between a utility and a
cyclical manufacturer. An industry median can. This is the single biggest
accuracy improvement available.

It is also where a Big Data component genuinely belongs, because it is the
first part of the project that *needs* scale. One company needs seven numbers.
A credible industry median needs 20+ companies per sector, which means
hundreds of companies, which means batching, caching and rate limits — real
data engineering with a real reason for it.

**Build order:**

1. Pick ~30 tickers across 3–4 industries in a JSON file.
2. Loop with the existing `load_history()`, cache each result to
   `data/cache/<TICKER>.json`. A 10-K does not change, so never re-fetch.
3. Compute metrics with the existing `compute_all_metrics()` — **no changes
   needed to stages 1 or 2**, which is the payoff of keeping them pure.
4. Group by industry, take the median of each metric.
5. Add a section 2b to the report: company vs median vs percentile.

**Two statistical points worth getting right:**

- **Median, not mean.** Credit metrics have brutal outliers — one company with
  near-zero EBITDA produces a 400x leverage ratio that would wreck a mean.
- **Drop the uncomputable; never zero it.** A company whose leverage is `None`
  because EBITDA is negative must be *excluded* from the median. But record how
  many you dropped and report it — a sector where half the companies have
  negative EBITDA is itself the finding.

`peers.py` already contains tested `median()` and `compare_to_peers()`
functions. Nothing else is built.

---

## Limitations

Be able to state these; knowing what a tool cannot do is most of
understanding it.

1. **No debt maturity dates.** The most important thing this tool cannot see.
   6x leverage with nothing due for five years is survivable; the same
   leverage with a large maturity next year is urgent.
2. **No covenant information.** A breach can let lenders demand immediate
   repayment, which is often what actually starts a restructuring.
3. **No industry context.** Absolute thresholds applied to every company. See
   the Big Data extension.
4. **No sense of EBITDA quality.** Reported figures may include generous
   add-backs. Every ratio here rests on that denominator.
5. **No liquidity picture.** Undrawn revolving credit facilities do not appear
   in these seven fields, and they can be the difference between a problem and
   a crisis.
6. **Cannot tell cyclical from structural.** The judgement that matters most,
   and no ratio answers it.
7. **Annual data only.** A company can deteriorate fast inside a fiscal year.
8. **One company at a time.** No peer or industry comparison yet — see the Big
   Data extension above. This is the limitation that most affects the accuracy
   of the thresholds.
9. **Captive finance arms break Debt/EBITDA entirely.** A car maker that lends
   customers the money to buy its cars carries that loan book's funding as
   debt on its own balance sheet. The loan book earns *interest income*, which
   is not in EBITDA — so the numerator counts the finance debt while the
   denominator ignores the finance earnings. Ford screens at roughly **39x**
   for exactly this reason, which is not a calculation error and not a sign of
   distress. Banks, insurers and leasing companies behave the same way. The
   app flags any reading above 15x with a red warning rather than letting you
   read it at face value; a real analyst splits the industrial business from
   the finance business using segment disclosures and computes leverage on the
   industrial side alone.

---

## Disclaimer

A learning project. Not investment advice, not a credit rating, and not a
prediction of bankruptcy. The bundled `EXMPL` and `HEALTHY` data are
**synthetic** and describe no real company.
