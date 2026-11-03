# E-015 author brief (TP-042)

You are writing a held-out evaluation battery for a numeric fact-checker. The checker reads an analyst-style answer and a session ledger (the tool results the analyst saw), and decides, for every number in the answer, whether the ledger supports it. You must not look at how the checker works.

## Rules of access

- Read only two files: this brief and `test/offline/fixtures/e015_ledgers.yaml`.
- Do not open anything under `src/`, `test/` (other than the ledger file), `docs/`, `prompts/`, `sessions/` or `data/`, do not open any other fixture, and do not search the repository.
- Write exactly one file: `test/offline/fixtures/e015_heldout.yaml`.

## The ledgers

`e015_ledgers.yaml` holds two session ledgers under `ledgers:`. Each maps a tool-call key (`turn-0001/<tool>#<n>`) to that tool's result:

- `byd_report`: the latest quote, the indicator snapshot, the fundamentals summary (which says no fundamentals are stored) and five recent headlines for 1211.HK (BYD Company Ltd).
- `perf_pair`: the latest quotes for 0700.HK (Tencent Holdings Ltd) and HSI.INDX (Hang Seng Index), their `market.performance` results, and Tencent's indicator snapshot.

Indicator rows are `{metric, value, unit, window}`. A `fraction` value of -0.36 may be written as -36%. A performance window's `change_pct` is already a percent: -4.8828 means a fall of 4.8828%. A headline's `sentiment` holds `polarity`, `neg`, `neu` and `pos`. No ledger contains a price target or a forecast.

## What to write

Write realistic English analyst prose about these ledgers. Use short answers of one to four sentences, Markdown tables and bullet lists, the way a careful analyst writing a report would. Each answer cites exactly one ledger. Write correct claims and wrong claims, and label every number.

A claim is **correct** when the ledger supports that number for the subject and the quantity the sentence attributes it to. These variants still count as correct:

- rounding to the precision written;
- a fraction written as a percent;
- a fall written as a positive number with a word saying it fell (a `change_pct` of -4.8828 written "fell 4.88%" or "down 4.9%"), or as a signed number ("-4.88%");
- a count of sessions, headlines or windows that the ledger states;
- dates written in any common form;
- digits inside a headline title that is reproduced exactly, in straight quotes, curly quotes, backticks, or as the whole content of a table cell (the digits are part of the quoted title, not a claim of their own).

A claim is **wrong** in any of these cases:

- the value is not in the ledger;
- the value belongs to another company or index;
- the value belongs to another quantity (the high given as the low, a 5-session change given as the 20-session change, the negative-sentiment share given as the polarity);
- the direction is wrong (a fall written as a rise, or the reverse);
- the value is more precise than the ledger supports;
- the value is computed from ledger values but does not itself appear in the ledger;
- a headline title is reproduced with a digit changed.

Numbers that are **not claims** must still be listed, with `correct: true` and `kind: identifier`: section references (§2), list enumerators ("(1)", "(2)", "1)"), and step numbers ("Step 2").

## Classes to cover

1. `inline_list`: several quote fields on one line, separated by middle dots (·), bullets (•) or vertical bars, for example "Open 74.6 · High 74.9 · Low 73.3 · Close 73.9". Write correct lists, and wrong ones in which one value sits under the wrong field.
2. `table_count`: tables with one row per metric (volatility, drawdown, a performance window) and a cell giving the window as a session count or a date range, for example "| Max drawdown | -36.1% | 259 sessions |". Write correct counts, wrong counts, and wrong metric values in the same rows.
3. `reference`: answers that cite their own sections (§2, §4) or number their points ("(1) ... (2) ...", "1) ... 2) ...", "Step 3:"), alongside real numeric claims in the same sentences, some correct and some wrong.
4. `quoted_title`: headlines reproduced in backticks, in quotes, and as whole table cells, including the titles that contain digits. Include titles with one digit changed (wrong), and digits from a title used as if they were data, such as "gas vehicles fell below 50% of sales" (wrong: a headline asks it, no ledger value states it).
5. `sentiment_component`: answers that give a headline's polarity together with its neg, neu or pos share in the same sentence ("polarity -0.768, with neg 0.224 and neu 0.776"), correct and wrong, including a share given to the wrong component.
6. `decline_sign`: performance windows described in words ("fell 4.88% over the last 20 sessions", "rose 1.89% over 5 sessions", "down 10.6% across 250 sessions", "the index gained 3.34% over the month"), and in signed form. Include wrong directions, a window's change given to another window, and Tencent's change given to the index.
7. `general`: controls across the rest (prices, volume, volatility, drawdown, dates, the headline count, the session count), correct and wrong.

## Counts

- At least 80 labeled claims in total.
- At least 30 of them wrong.
- At least 8 claims in each of the six named classes 1 to 6.

## Format

```yaml
# E-015 held-out battery (TP-042), written by a separately briefed author from the frozen ledgers only.
items:
  - id: G001
    ledger: byd_report
    text: |-
      BYD's last bar: Open 74.6 · High 74.9 · Close 73.9.
    claims:
      - {text: "74.6", correct: true, kind: exact, class: inline_list}
```

- `id`: G001, G002 and so on.
- `ledger`: `byd_report` or `perf_pair`.
- `claims`: every number in `text`, in order of appearance, including dates, counts, identifiers and the digits inside quoted titles. Leave out numbers that are part of a ticker (1211.HK, SEHK:1211) or of the index code.
- `text` of a claim: the exact substring as written in the answer, including a % sign or a currency word that is part of it ("4.88%"). A number inside a quoted title is its own claim, written as it appears in the title ("50%", "3", "2026-2030"). If the same substring occurs twice in one answer, write the answer so that it does not.
- `correct`: true or false.
- `kind`: a short tag such as exact, rounding, unit_conversion, sign_word, count, temporal, sentiment, identifier, quoted_title, fabricated, misattributed, wrong_field, wrong_direction, over_precise, derived, altered_title.
- `class`: one of the seven class names above.
- Add a short trailing `# comment` on wrong claims saying why.

Write the file once. When you are done, report the counts per class and in total.
