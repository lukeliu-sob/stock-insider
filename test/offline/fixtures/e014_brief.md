# E-014 author brief (TP-039)

You are writing a held-out evaluation battery for a numeric fact-checker. The checker reads an analyst-style answer and a session ledger (the tool results the analyst saw), and decides, for every number in the answer, whether the ledger supports it. You must not look at how the checker works.

## Rules of access

- Read only two files: this brief and `test/offline/fixtures/e013_ledgers.yaml`.
- Do not open anything under `src/`, `test/` (other than the ledger file), `docs/`, `prompts/`, `sessions/` or `data/`, do not open any other fixture, and do not search the repository.
- Write exactly one file: `test/offline/fixtures/e014_heldout.yaml`.

## The ledgers

`e013_ledgers.yaml` holds five session ledgers under `ledgers:`. Each maps a tool-call key (`turn-0001/<tool>#<n>`) to that tool's result:

- `hk_pair`: quotes and indicators for 0700.HK (Tencent) and 1211.HK (BYD), and recent news for Tencent.
- `us_pair`: quotes, indicators and fundamentals for AAPL.US (Apple) and TGT.US (Target Corp).
- `apple_only`: Apple's quote and indicators only.
- `session`: the watchlist, the sync status and a news search.
- `unverified`: one quote for 9988.HK, whose name is not verified.

Indicator rows are `{metric, value, unit, window}`. A `fraction` or `ratio` value of 0.0545 may be written as 5.45%. The `yoy_growth` metric (found under `growth.revenue_yoy`) is the year-over-year revenue growth. Fundamentals rows hold quarterly `totalRevenue`, `netIncome`, `grossProfit`, and balance-sheet `totalAssets` and `totalStockholdersEquity`. No ledger contains an analyst price target.

## What to write

Write realistic English analyst prose about these ledgers: short answers of one to four sentences, plus some small Markdown tables. Each answer cites exactly one ledger. Write correct claims and wrong claims, and label every number.

A claim is **correct** when the ledger supports that number for the subject and the quantity the sentence attributes it to. These variants still count as correct:

- rounding to the precision written;
- a fraction written as a percent;
- scale words (94,036,000,000 written as 94.0 billion);
- a scale stated once for a whole table, in its title or header, applying to every cell it covers;
- dates written in any common form.

A claim is **wrong** in any of these cases:

- the value is not in the ledger;
- the value belongs to another company;
- the value belongs to another quantity;
- the value is more precise than the ledger supports;
- the value is computed from ledger values but does not itself appear in the ledger;
- the claim concerns a company that has no data in the cited ledger;
- the claim is a price target or fair value, because no ledger holds one.

## Classes to cover

1. `growth_phrasing`: revenue growth stated in varied everyday words, for example "grew 9.56% year on year", "rose 9.6% from a year earlier", "up 9.56% y-o-y", "a 9.56% increase in revenue", "revenue fell 1.18% versus the prior-year quarter", "revenue declined by 1.2%". Mix correct and wrong claims, including:
   - a growth rate stated as a revenue amount ("revenue of 9.56 billion");
   - a revenue amount stated as a growth rate;
   - one company's growth given to the other;
   - an over-precise growth figure.
2. `name_cue_collision`: answers citing `us_pair` in which Target Corp appears as a company, in prose and as a table row or column label, next to:
   - genuine price-target or fair-value claims (always wrong, since no ledger holds one), such as "a price target of USD 160" or "Target's target price of 150";
   - the word "target" used as a verb ("investors targeting growth").
   
   Include correct and wrong values for Target Corp in tables.
3. `general`: controls across the rest (prices, volume, margins, ROE, volatility, drawdown, sentiment, counts, fundamentals, the sync budget, dates), correct and wrong.

## Counts

- At least 60 labeled claims in total.
- At least 25 of them wrong.
- At least 15 claims in each of `growth_phrasing` and `name_cue_collision`.

## Format

```yaml
# E-014 held-out battery (TP-039), written by a separately briefed author from the frozen ledgers only.
items:
  - id: F001
    ledger: us_pair
    text: |-
      Apple's revenue grew 9.56% year on year.
    claims:
      - {text: "9.56%", correct: true, kind: unit_conversion, class: growth_phrasing}
```

- `id`: F001, F002 and so on.
- `ledger`: one of the five ledger names.
- `claims`: every number in `text`, in order of appearance, including dates, counts and numbers inside tables. Leave out numbers that are part of a ticker (0700.HK) or a fiscal label such as Q2 or FY2026.
- `text` of a claim: the exact substring as written in the answer. If the same substring occurs twice in one answer, write the answer so that it does not.
- `correct`: true or false.
- `kind`: a short tag such as exact, rounding, unit_conversion, scale_word, temporal, count, sentiment, fabricated, misattributed, wrong_field, over_precise, derived, no_evidence, price_target.
- `class`: one of the three class names above.
- Add a short trailing `# comment` on wrong claims saying why.

Write the file once. When you are done, report the counts per class and in total.
