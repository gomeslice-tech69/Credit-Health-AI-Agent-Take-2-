"""
Question bank: private credit and restructuring fundamentals.

Every question is tied to something the tool itself computes or displays, so
studying the quiz and reading the screener reinforce each other. The
explanations say why the wrong answers are wrong, because in credit the
plausible-but-wrong answer is usually the more instructive one.

Questions carry a difficulty so a session can start with vocabulary and work
up to the judgement calls, and a topic so a reader can drill one area.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

BASIC = "Basic"
INTERMEDIATE = "Intermediate"
ADVANCED = "Advanced"

LEVELS = [BASIC, INTERMEDIATE, ADVANCED]


@dataclass
class Question:
    """One multiple-choice question.

    `answer` is the index into `options`. `why_wrong` maps an option index to
    the reason it is wrong -- the part that actually teaches.
    """

    topic: str
    level: str
    prompt: str
    options: List[str]
    answer: int
    explanation: str
    why_wrong: Dict[int, str]

    @property
    def correct_option(self) -> str:
        return self.options[self.answer]


QUESTIONS: List[Question] = [

    # ---------------------------------------------------------------- basics
    Question(
        topic="Metrics", level=BASIC,
        prompt="What does EBITDA add back to net income?",
        options=[
            "Interest, taxes, depreciation and amortization",
            "Interest, taxes, dividends and capex",
            "Taxes, depreciation, capex and working capital",
            "Interest, depreciation, inventory and receivables",
        ],
        answer=0,
        explanation=(
            "Interest depends on how the company chose to borrow, taxes on "
            "jurisdiction, and depreciation and amortization are accounting "
            "charges where no cash leaves this year. Strip all four and you "
            "get a rough proxy for cash the core business generates before "
            "financing decisions."),
        why_wrong={
            1: "Capex and dividends are never added back. Ignoring capex is "
               "EBITDA's main weakness, not part of its definition.",
            2: "Working capital movements belong in cash flow, not EBITDA.",
            3: "Inventory and receivables are balance-sheet items.",
        }),

    Question(
        topic="Metrics", level=BASIC,
        prompt="Net Debt / EBITDA of 4.5x means roughly what?",
        options=[
            "Debt is 4.5% of earnings",
            "It would take about 4.5 years of EBITDA to repay debt net of cash",
            "The company earns 4.5 times its interest bill",
            "Debt has grown 4.5 times since last year",
        ],
        answer=1,
        explanation=(
            "Read leverage as years. At 4.5x, every dollar of EBITDA for four "
            "and a half years would be needed to clear the debt, after "
            "crediting cash already on hand."),
        why_wrong={
            0: "It is a multiple, not a percentage.",
            2: "That is interest coverage, a different ratio.",
            3: "Growth is not what a leverage multiple measures.",
        }),

    Question(
        topic="Metrics", level=BASIC,
        prompt="Why subtract cash when calculating net debt?",
        options=[
            "Accounting standards require it",
            "Cash could repay borrowings tomorrow, so it offsets the burden",
            "It makes companies look healthier",
            "Cash earns interest that cancels debt interest",
        ],
        answer=1,
        explanation=(
            "A company holding $2bn of cash against $5bn of debt owes $3bn in "
            "economic terms. Net debt is usually the more realistic measure, "
            "and credit agreements are often written against it."),
        why_wrong={
            0: "Net debt is a convention, not a required GAAP line.",
            2: "It does lower the ratio, but the reason is economic. Watch "
               "whether the cash is genuinely available — cash trapped in a "
               "foreign subsidiary cannot repay anything.",
            3: "Interest earned on cash rarely matches interest paid on debt.",
        }),

    Question(
        topic="Restructuring", level=BASIC,
        prompt="What is Chapter 11?",
        options=[
            "Liquidation — the company is sold off and ceases to exist",
            "Reorganisation — the company keeps operating while it restructures debt",
            "A credit rating one notch below investment grade",
            "A covenant type in leveraged loans",
        ],
        answer=1,
        explanation=(
            "Chapter 11 lets a company keep trading while it renegotiates "
            "with creditors. Chapter 7 is the liquidation chapter. Most large "
            "US restructurings run through Chapter 11."),
        why_wrong={
            0: "That is Chapter 7.",
            2: "Ratings use letters, not chapters.",
            3: "Chapter 11 is a bankruptcy code section, not a loan term.",
        }),

    Question(
        topic="Private credit", level=BASIC,
        prompt="What distinguishes private credit from a syndicated bank loan?",
        options=[
            "Private credit is always secured; bank loans never are",
            "A fund lends directly and usually holds the loan, rather than a "
            "bank originating and distributing it",
            "Private credit is only available to public companies",
            "Private credit loans are always smaller than $1m",
        ],
        answer=1,
        explanation=(
            "Direct lending means the fund originates and holds. No "
            "syndication desk, no ratings requirement, and terms negotiated "
            "bilaterally — which is why these loans are faster to arrange and "
            "usually priced higher."),
        why_wrong={
            0: "Both are typically secured. Security is not the distinction.",
            2: "Private credit lends overwhelmingly to private, "
               "sponsor-backed companies.",
            3: "Direct lending deals routinely run into the billions.",
        }),

    # --------------------------------------------------------- intermediate
    Question(
        topic="Metrics", level=INTERMEDIATE,
        prompt="A company's EBITDA falls 20%. Its debt is unchanged. Roughly "
               "what happens to Debt / EBITDA?",
        options=["Falls about 20%", "Rises about 20%", "Rises about 25%",
                 "Unchanged, since debt did not move"],
        answer=2,
        explanation=(
            "Dividing by 0.8 multiplies the ratio by 1.25. Earnings fall 20%, "
            "leverage rises 25%. That asymmetry is exactly why leverage "
            "creates fragility: the denominator shrank while the numerator "
            "stood still."),
        why_wrong={
            0: "The ratio moves the opposite way to earnings.",
            1: "Close, but the arithmetic is 1/0.8, not 1.2.",
            3: "The ratio depends on both inputs, not just debt.",
        }),

    Question(
        topic="Metrics", level=INTERMEDIATE,
        prompt="Interest coverage falls below 1.0x. What does that mean?",
        options=[
            "The company has more debt than equity",
            "Operating earnings no longer cover the interest bill at all",
            "The company has breached a covenant",
            "Debt exceeds one year of revenue",
        ],
        answer=1,
        explanation=(
            "Below 1.0x, EBITDA is smaller than interest expense. The "
            "shortfall has to come from cash reserves, asset sales or new "
            "borrowing. Interest is due on fixed dates and missing it is an "
            "event of default."),
        why_wrong={
            0: "That is a debt-to-equity question.",
            2: "It often triggers one, but coverage and covenants are "
               "different things — covenant levels are set in the credit "
               "agreement.",
            3: "Revenue does not appear in the coverage ratio.",
        }),

    Question(
        topic="Restructuring", level=INTERMEDIATE,
        prompt="What is a restructuring support agreement (RSA)?",
        options=[
            "A government programme supporting distressed firms",
            "A deal with creditors setting out the restructuring terms before "
            "or during a filing",
            "An insurance policy against default",
            "A clause requiring a company to maintain leverage below a level",
        ],
        answer=1,
        explanation=(
            "An RSA means the outcome has been negotiated rather than "
            "litigated. It commits signing creditors to support a plan, and "
            "it often appears days before a Chapter 11 filing — which is why "
            "it is worth watching as a leading signal."),
        why_wrong={
            0: "RSAs are private agreements between a company and creditors.",
            2: "That describes a credit default swap.",
            3: "That is a financial covenant.",
        }),

    Question(
        topic="Private credit", level=INTERMEDIATE,
        prompt="What is debtor-in-possession (DIP) financing?",
        options=[
            "A loan taken before bankruptcy to avoid filing",
            "New money lent to a company already in bankruptcy, ranking ahead "
            "of existing debt",
            "Equity injected by existing shareholders",
            "A government guarantee on bank deposits",
        ],
        answer=1,
        explanation=(
            "DIP lenders get priority over pre-petition creditors, which is "
            "what makes lending into a bankruptcy rational. It is a private "
            "credit specialism, and the terms say a lot about how much value "
            "lenders believe is left."),
        why_wrong={
            0: "DIP financing happens after the petition, not before.",
            2: "DIP financing is debt, and shareholders usually recover "
               "nothing in Chapter 11.",
            3: "Unrelated — that is deposit insurance.",
        }),

    Question(
        topic="Analysis", level=INTERMEDIATE,
        prompt="Free cash flow is negative while debt rises each year. Why is "
               "that combination dangerous?",
        options=[
            "It always means fraud",
            "Leverage rises mechanically every year even with no single bad event",
            "It means the company is growing too fast to matter",
            "It has no effect as long as EBITDA is positive",
        ],
        answer=1,
        explanation=(
            "The shortfall is funded with borrowing, so debt grows while the "
            "earnings servicing it do not. Leverage climbs year after year "
            "with nothing dramatic happening — the most common path into "
            "distress."),
        why_wrong={
            0: "Negative free cash flow is often a deliberate investment "
               "programme. It is a question, not an accusation.",
            2: "Growth can explain it, but the debt still compounds.",
            3: "Positive EBITDA does not prevent the spiral.",
        }),

    # -------------------------------------------------------------- advanced
    Question(
        topic="Analysis", level=ADVANCED,
        prompt="Ford screens at roughly 39x Net Debt / EBITDA. What is the "
               "most likely explanation?",
        options=[
            "Ford is about to file for bankruptcy",
            "A data error in the filing",
            "Its captive finance arm's debt funds a loan book whose income sits "
            "outside EBITDA",
            "Ford has almost no EBITDA",
        ],
        answer=2,
        explanation=(
            "Ford Credit's borrowing sits on Ford's balance sheet, but the "
            "interest income it earns is not in EBITDA. The numerator counts "
            "the finance debt while the denominator ignores the finance "
            "earnings. Banks, insurers and leasing companies do the same "
            "thing. A real analyst splits the industrial segment out."),
        why_wrong={
            0: "Ford is not in distress. The ratio is the wrong lens, not a "
               "warning.",
            1: "The arithmetic is correct. The interpretation is what breaks.",
            3: "Ford's EBITDA is substantial — it is the debt side that is "
               "distorted.",
        }),

    Question(
        topic="Analysis", level=ADVANCED,
        prompt="Two data sources give the same company different total debt, "
               "changing its rating. What is usually the cause?",
        options=[
            "One source is simply wrong",
            "They define total debt differently — typically operating leases",
            "Currency conversion",
            "One is measuring a different fiscal year",
        ],
        answer=1,
        explanation=(
            "Total debt is a definition, not a fact. Some sources include "
            "operating lease liabilities and some do not; finance leases are "
            "usually counted by both. The arithmetic is identical — the "
            "inputs are not. This is why professionals state their "
            "definitions."),
        why_wrong={
            0: "Both can be internally consistent and still disagree.",
            2: "Possible across currencies, but not the usual cause for a US "
               "filer.",
            3: "Worth checking, but a persistent gap points to definitions.",
        }),

    Question(
        topic="Restructuring", level=ADVANCED,
        prompt="Why do debt maturity dates matter more than the leverage ratio?",
        options=[
            "They do not — leverage is the better measure",
            "Companies fail when they miss a payment on a date, not when a "
            "ratio crosses a threshold",
            "Maturities determine the credit rating",
            "Because interest is only paid at maturity",
        ],
        answer=1,
        explanation=(
            "Leverage measures size; maturities measure timing. 6x leverage "
            "with nothing due for five years is survivable. The same 6x with "
            "a large maturity next year is urgent. Default is a missed "
            "payment on a specific day."),
        why_wrong={
            0: "Leverage is necessary but not sufficient — it is blind to "
               "timing.",
            2: "Ratings consider maturities among many factors.",
            3: "Interest is typically paid periodically throughout the life "
               "of the debt.",
        }),

    Question(
        topic="Private credit", level=ADVANCED,
        prompt="Why has private credit grown so quickly since 2010?",
        options=[
            "Private credit loans are risk-free",
            "Post-crisis bank regulation made leveraged lending costlier for "
            "banks, and borrowers valued speed and certainty",
            "Governments mandated it",
            "It only lends to investment-grade companies",
        ],
        answer=1,
        explanation=(
            "Capital rules made it expensive for banks to hold leveraged "
            "loans, while sponsors wanted certainty of execution without a "
            "syndication process or a public rating. Funds filled the gap, and "
            "investors accepted illiquidity for yield."),
        why_wrong={
            0: "These are typically sub-investment-grade borrowers. The risk "
               "is real; it is priced.",
            2: "The growth was market-driven, not mandated.",
            3: "Private credit lends mainly below investment grade.",
        }),

    Question(
        topic="Analysis", level=ADVANCED,
        prompt="A screening tool reports leverage as 'not meaningful' when "
               "EBITDA is negative. Why refuse rather than print the number?",
        options=[
            "The calculation would fail",
            "A negative multiple looks healthier than a high positive one, "
            "which inverts the conclusion",
            "Negative EBITDA is always a data error",
            "Regulators prohibit it",
        ],
        answer=1,
        explanation=(
            "Debt of $500m over EBITDA of −$100m gives −5.0x, which sorts as "
            "less leveraged than a company at 6.0x. In reality it is far "
            "worse: no multiple of negative earnings can repay debt. Refusing "
            "is the honest answer."),
        why_wrong={
            0: "The arithmetic works fine. That is the problem.",
            2: "Negative EBITDA is real and common in distress.",
            3: "No regulation applies to a screening tool.",
        }),
]


def topics() -> List[str]:
    """Every topic in the bank."""
    return sorted({q.topic for q in QUESTIONS})


def select(level: Optional[str] = None, topic: Optional[str] = None,
           count: int = 5, seed: Optional[int] = None) -> List[Question]:
    """Pick questions matching the filters.

    Returns fewer than `count` when the filters leave fewer, rather than
    padding with repeats -- answering the same question twice in one round
    teaches nothing.
    """
    pool = [q for q in QUESTIONS
            if (level is None or q.level == level)
            and (topic is None or q.topic == topic)]
    if not pool:
        return []
    rng = random.Random(seed)
    return rng.sample(pool, min(count, len(pool)))


def grade(score: int, total: int) -> str:
    """A short verdict on a finished round."""
    if total == 0:
        return "No questions answered."
    ratio = score / total
    if ratio == 1:
        return "Full marks."
    if ratio >= 0.8:
        return "Strong — the fundamentals are there."
    if ratio >= 0.6:
        return "Reasonable. Read the explanations on the ones you missed."
    if ratio >= 0.4:
        return "Worth another round. The explanations are where the learning is."
    return "Start with the Basic level and work up."
