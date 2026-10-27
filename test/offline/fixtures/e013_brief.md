# E-013 author brief (TP-025 stage 5)

You are writing a held-out evaluation battery for a numeric fact-checker. The checker reads an analyst-style answer and a session ledger (the tool results the analyst saw), and decides, for every number in the answer, whether the ledger supports it. You must not look at how the checker works.

## Rules of access

- Read only two files: this brief and `test/offline/fixtures/e013_ledgers.yaml`.
- Do not open anything under `src/`, `test/` (other than the ledger file), `docs/`, `prompts/`, `sessions/` or `data/`, and do not search the repository.
- Write exactly one file: `test/offline/fixtures/e013_heldout.yaml`.

## The ledgers

`e013_ledgers.yaml` holds five session ledgers under `ledgers:`. Each maps a tool-call key (`turn-0001/<tool>#<n>`) to that tool's result:

- `hk_pair`: quotes and indicators for 0700.HK (Tencent) and 1211.HK (BYD), and recent news for Tencent.
- `us_pair`: quotes, indicators and fundamentals for AAPL.US (Apple) and TGT.US (Target).
- `apple_only`: Apple's quote and indicators only.
- `session`: the watchlist, the sync status and a news search.
- `unverified`: one quote for 9988.HK, whose `official_name` is `null` (the name is not verified; you may know the company as Alibaba).

Indicator rows are `{metric, value, unit, window}`. A `fraction` or `ratio` value of 0.0545 may be written as 5.45%. `max_drawdown` values are negative fractions; writing a drawdown as a positive percent ("a 10.5% drawdown") is correct.

## What to write

Write realistic English analyst prose about these ledgers: short answers of one to four sentences, plus a few small Markdown tables. Each answer cites exactly one ledger. Write correct claims and wrong claims, and label every number.

A claim is **correct** when the ledger supports that number for the subject and the quantity the sentence attributes it to. These variants still count as correct:

- rounding to the precision written (643.06 written as 643.1 or 643);
- a fraction written as a percent;
- scale words (17,451,021 shares written as 17.45 million);
- dates written in any common form.

A claim is **wrong** in any of these cases:

- the value is not in the ledger (fabricated);
- the value belongs to another company (misattributed);
- the value belongs to another quantity (for example the open given as the close);
- the value is more precise than the ledger supports;
- the value is computed from ledger values but does not itself appear in the ledger (a difference, a ratio, a sum: kind `derived`);
- the claim concerns a company that has no data in the cited ledger, even if the number happens to appear in it for someone else.

## Classes to cover

Cover every class below at least five times, mixing correct and wrong claims within each:

1. `name_misattribution`: two companies in the ledger, a number attributed by company name (not ticker) to the wrong one.
2. `postposed_subject`: the company is named after the number ("18.2 million shares for BYD", "a 24.9% net margin at Apple"). Include correct and wrong cases.
3. `absent_company`: a company that has no data in the cited ledger (for example Tencent or Target in an answer citing `apple_only`).
4. `unverified_name`: answers citing `unverified` that name the company in words (Alibaba) rather than by ticker.
5. `common_word_name`: answers citing `us_pair` that use "target" as an ordinary word ("price target", "targeted", "Target" at the start of a sentence used as a common noun or verb) next to real numbers.
6. `table`: Markdown tables with company rows and quantity columns.

Also cover, at least twice each: exact values, rounding, percent conversion, scale words, dates, counts (articles, watchlist symbols, sessions), news sentiment readings, fundamentals (revenue, net income, equity), the sync budget (API calls used, remaining, cap), over-precise values, fabricated values, wrong-field values and derived values.

## Counts

- At least 80 labeled claims in total.
- At least 35 of them wrong.
- At least 5 claims in each of the six classes above.

## Format

```yaml
# E-013 held-out battery (TP-025 stage 5), written by a separately briefed author from the frozen ledgers only.
items:
  - id: E001
    ledger: hk_pair
    text: |-
      Tencent closed at HKD 643.06, while BYD finished at 69.44.
    claims:
      - {text: "643.06", correct: true, kind: exact, class: name_misattribution}
      - {text: "69.44", correct: true, kind: exact, class: name_misattribution}
```

- `id`: E001, E002 and so on.
- `ledger`: one of the five ledger names.
- `claims`: every number in `text`, in order of appearance, including dates, counts and numbers inside tables. Leave out numbers that are part of a ticker (0700.HK) or a fiscal label such as Q2 or FY2026.
- `text` of a claim: the exact substring as written in the answer. If the same substring occurs twice in one answer, write the answer so that it does not.
- `correct`: true or false.
- `kind`: a short tag such as exact, rounding, unit_conversion, scale_word, temporal, count, sentiment, fabricated, misattributed, wrong_field, over_precise, derived, no_evidence.
- `class`: one of the six class names above, or `general`.
- Add a short trailing `# comment` on wrong claims saying why.

Write the file once. When you are done, report the counts per class and in total.
