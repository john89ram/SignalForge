# Stage 3 Handoff Review — Hermes Implementation Readiness Notes

**Timestamp (UTC):** 2026-05-25T19:30:38Z  
**Prepared by:** Hermes  
**Audience:** Senior Dev, Code Auditor  
**Repo:** SignalForge / market-funnel  
**Purpose:** Detailed GitHub-visible handoff after reviewing the Stage 3 directory, Senior Dev/auditor notes, build brief, current Stage 2 live output contract, and existing Stage 3 code path.

---

## 1. Executive summary

Stage 3 is ready to build as a batch runner. The existing DCF / valuation engine already lives in `screener.py`; the missing piece is the canonical runner at:

```text
stages/stage3/code/run_stage3.py
```

The runner should mirror the Stage 2 runner pattern:

1. read an upstream CSV,
2. process symbols with isolated per-symbol error handling,
3. write a deterministic report CSV,
4. emit a human-readable run log,
5. emit a JSONL audit trail,
6. include regression tests before live use.

Important: Stage 3 should **not** rewrite valuation logic, tune DCF thresholds to force more entries, or add trade-construction features. It should only answer:

> Is this stock worth owning at today’s price?

The downstream trade layer will handle strikes, DTE, premium yield, earnings-date clearance, portfolio context, and AI trade confirmation.

---

## 2. Files reviewed

### Stage 3 directory

Reviewed current Stage 3 structure:

```text
stages/stage3/
├── README.md
├── mission.md
├── verdict.md
├── code/
│   └── README.md
├── output/
│   └── README.md
└── audit_logs/
    ├── README.md
    └── stage3_build_brief_20260525.md
```

### Stage 3 specification / handoff documents

Reviewed:

- `stages/stage3/mission.md`
- `stages/stage3/code/README.md`
- `stages/stage3/audit_logs/stage3_build_brief_20260525.md`
- `stages/stage3/verdict.md`
- `stages/stage3/output/README.md`
- `stages/stage3/audit_logs/README.md`

### Upstream Stage 2 live output

Reviewed current live Stage 2 artifact:

- `stages/stage2/output/Stage2_Report.csv`

This matters because Stage 3’s input contract must match the actual Stage 2 report currently committed to GitHub, not just the proposed names in the brief.

### Existing implementation dependencies

Reviewed relevant `screener.py` code path:

- `TickerAnalysis`
- `QuoteSnapshot`
- `SECFacts`
- `load_sec_companyfacts()`
- `parse_finviz_quote()`
- `stage3_analysis()`
- `stage3_share_count()`
- `summary_verdict()`
- existing Stage 3 CSV helpers

---

## 3. Current Stage 3 mission as understood

Stage 3 is the final pre-trade fundamental valuation filter.

Stage 2 answers:

> Is this stock behaving correctly as an options premium vehicle?

Stage 3 answers:

> Would I actually want to own this stock if assigned?

This is especially important for the Wheel strategy because a cash-secured put can become assigned stock. Stage 3 protects against high-IV premium traps where the options premium looks attractive but ownership risk is not justified by fundamentals.

Stage 3 does not make the final trade decision. It is a valuation and ownership-quality gate.

---

## 4. Confirmed build target

Build this file:

```text
stages/stage3/code/run_stage3.py
```

The runner should:

1. Read `stages/stage2/output/Stage2_Report.csv`.
2. Exclude Stage 2 `Eliminated` rows.
3. Process eligible tiers in cascade order:
   - `Diamond`
   - `Strong`
   - `Standard`
   - `Watch`
4. Fetch fresh Finviz quote data per symbol for current price.
5. Fetch SEC companyfacts per symbol.
6. Reconstruct a `TickerAnalysis` object.
7. Preserve Stage 2 kill/flag context on that object.
8. Call existing `stage3_analysis()`.
9. Call existing `summary_verdict()`.
10. Write `stages/stage3/output/Stage3_Report.csv`.
11. Write `stages/stage3/audit_logs/stage3_run_<timestamp>.log`.
12. Write `stages/stage3/audit_logs/stage3_run_<timestamp>.jsonl`.
13. Support offline/contract testing mode separately from live validation.
14. Ship with regression tests in `tests/test_stage3_runner.py`.

---

## 5. Existing engine: do not rewrite

The build brief is explicit and I agree: the DCF engine already exists and should be imported.

Relevant imports expected from `screener.py`:

```python
from screener import (
    TickerAnalysis,
    QuoteSnapshot,
    SECFacts,
    load_sec_companyfacts,
    parse_finviz_quote,
    stage3_analysis,
    stage3_share_count,
    summary_verdict,
    HTTP,
)
```

The runner is a pipeline wrapper, not a new model.

---

## 6. Stage 3 valuation method

Current Stage 3 methodology from mission/build docs:

### Category A

Profitable or FCF-positive names.

- Discount rate: 10%
- Margin-of-safety threshold: 80% of weighted fair value
- Scenario weights: 25% bear / 50% realistic / 25% bull

### Category B

Pre-profitable or cash-burning names.

- Discount rate: 15%
- Margin-of-safety threshold: 50% of weighted fair value
- Scenario weights: 42% bear / 46% realistic / 12% bull

### APLD exception

APLD receives a bespoke forward-buildout EV model in `screener.py` via:

```text
_apld_forward_buildout_stage3()
```

This is intentional because APLD is a construction-phase infrastructure developer and a plain FCF DCF can misread buildout economics.

---

## 7. Legal Stage 3 verdict labels

Stage 3 should emit exactly four verdict labels:

- `DIAMOND`
- `ENTRY`
- `NO ENTRY`
- `QC FAIL`

Meaning:

- `DIAMOND`: price is at or below MOS threshold and there are zero Stage 2 kills.
- `ENTRY`: price is at or below MOS threshold with 1–2 Stage 2 kills.
- `NO ENTRY`: price is above MOS threshold, or Stage 1/2 disqualified, or too many Stage 2 kills.
- `QC FAIL`: data failure, failed valuation, share denominator sanity failure, or zero/missing revenue.

Important naming collision:

- Stage 2 `Diamond` = HP-sieve tier.
- Stage 3 `DIAMOND` = valuation verdict.

These must remain distinct in every CSV column, log line, audit event, and review note. Use explicit field names:

- `stage2_tier`
- `stage3_verdict`

Never use a bare `diamond` field where the meaning is ambiguous.

---

## 8. Important input-contract mismatch found

The build brief specifies these Stage 2 input columns:

- `stage2_tier`
- `stage2_kills`
- `stage2_flags`

The current committed live Stage 2 report uses these columns instead:

- `hp_tier`
- `stage2_bad_text`
- `stage2_weak_text`

Current Stage 2 header begins with fields including:

```text
symbol
name
master_exchange
sector
industry
price_proxy
share_volume
market_cap
one_yr_target
stage1_pass
stage1_reasons
stage2_verdict
eligible_for_stage3
hp_tier
stage2_hp_total
stage2_hp_left
stage2_damage
stage2_score
stage2_bad_count
stage2_weak_count
stage2_bad_text
stage2_weak_text
...
```

### Recommendation

Do **not** change the already-audited Stage 2 output schema just to match the Stage 3 brief.

Instead, implement Stage 3 input aliases:

```text
stage2_tier   -> fallback to hp_tier
stage2_kills  -> fallback to stage2_bad_text
stage2_flags  -> fallback to stage2_weak_text
```

This preserves compatibility with the current audited Stage 2 artifact and still supports the brief’s preferred future naming if Stage 2 later adds/renames those columns.

### Why this matters

If the runner only looks for `stage2_kills`, it will see an empty value on today’s live CSV and accidentally treat every name as having zero Stage 2 kills. That can incorrectly upgrade names to Stage 3 `DIAMOND` verdicts.

This is the single most important schema issue to guard against before implementation.

---

## 9. Critical trap: propagate Stage 2 kills before `summary_verdict()`

`summary_verdict()` uses `len(analysis.stage2_kills)`.

If `analysis.stage2_kills` is empty because the runner failed to parse the Stage 2 row correctly, then names with 1–2 Stage 2 kills can be incorrectly upgraded from `ENTRY` to `DIAMOND` when price is below the MOS threshold.

Correct reconstruction must parse pipe-delimited kill text into the object before Stage 3 verdict calculation:

```python
analysis.stage2_kills = [
    item.strip()
    for item in stage2_kill_text.split("|")
    if item.strip()
]
```

For current Stage 2 CSV, `stage2_kill_text` should come from:

1. `row.get("stage2_kills")`, if present, else
2. `row.get("stage2_bad_text")`.

Same pattern for flags:

1. `row.get("stage2_flags")`, if present, else
2. `row.get("stage2_weak_text")`.

This should have a dedicated regression test.

---

## 10. Critical trap: use fresh price, not Stage 2 price

Stage 3’s MOS comparison depends on `analysis.quote.price`.

The Stage 2 CSV has `price_proxy`, but that can be stale. High-IV names can move enough intraday that stale price can flip:

- `NO ENTRY` -> `ENTRY`, or
- `ENTRY` -> `NO ENTRY`.

Therefore the runner must fetch fresh Finviz quote HTML for every processed symbol:

```python
finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
quote = parse_finviz_quote(finviz_html, symbol)
```

The Stage 2 price can be retained in output as a reference if desired, but it must not drive the Stage 3 MOS verdict in live mode.

---

## 11. Critical trap: `stage3_analysis()` return handling

The build brief warns correctly that `stage3_analysis()` usually returns a dict, including QC-failure dicts, not `None`.

The runner should handle both cases:

1. `stage3_analysis()` returns a dict with `verdict == "QC FAIL"`.
2. `stage3_analysis()` returns `None` unexpectedly.

Both should produce a valid Stage 3 CSV row.

Suggested behavior:

- If `stage3_analysis()` returns `None`, set `stage3_verdict = "QC FAIL"` and `qc_fail_reason = "stage3_analysis returned None"`.
- If it returns a dict with `verdict == "QC FAIL"`, keep the provided `qc_fail_reason`.
- Never let a `None` or QC-fail dict disappear from output.

---

## 12. Critical trap: isolate symbol errors

Any exception during a single symbol fetch or valuation should produce one `QC FAIL` row, not abort the run.

Required behavior:

- Wrap each symbol in `try/except`.
- Capture exception text in `qc_fail_reason`.
- Emit a `stage3_symbol_result` JSONL event for that symbol.
- Continue processing remaining symbols.

Acceptance criterion from the build brief:

> Zero unhandled exceptions — every error produces a `QC FAIL` row with a reason string.

This requires a regression test.

---

## 13. Cascade logic

The cascade exists to reduce unnecessary network calls.

Default cascade order:

1. Diamond
2. Strong
3. Standard
4. Watch

Default `--min-verdicts` should be `5`.

Actionable verdicts are:

- `DIAMOND`
- `ENTRY`

Cascade behavior:

1. Process all requested Diamond-tier rows.
2. Count `DIAMOND + ENTRY` verdicts.
3. If count is greater than or equal to `--min-verdicts`, stop.
4. Otherwise process Strong tier.
5. Repeat through Standard and Watch until threshold is met or tiers are exhausted.

Special case:

- `--min-verdicts 0` disables cascade and processes all eligible requested tiers.

This is useful for full validation, while the default cascade is better for production usage.

### Logging requirement

The log and JSONL summary must clearly state:

- tiers requested,
- tiers consumed,
- symbols processed per tier,
- actionable count after each tier,
- whether cascade stopped early,
- why it stopped or why it continued.

---

## 14. Recommended CLI

Expected live CLI shape:

```bash
python -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong,Standard,Watch
```

Recommended first validation run:

```bash
python -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond
```

Reason: run the six Stage 2 Diamond names first, confirm SEC/Finviz/DCF behavior is credible, then expand tiers.

---

## 15. Recommended Stage 3 report columns

The output contract should include at least:

```text
symbol
stage2_tier
stage2_score
stage2_hp_left
stage3_verdict
stage3_category
weighted_fair_value
mos_threshold
current_price
undervaluation_pct
bear_value
realistic_value
bull_value
qc_fail_reason
share_count_source
share_qc_detail
watch_signal
kill_signal
stage2_kills
stage2_flags
sector
iv_rank
implied_vol
```

### Note on current Stage 2 data availability

The current Stage 2 report does not expose `iv_rank` and `implied_vol` directly under those exact names. If those columns are missing, Stage 3 should leave those pass-through columns blank rather than crash.

Recommended pass-through helper behavior:

- `iv_rank`: use `row.get("iv_rank", "")` or blank.
- `implied_vol`: use `row.get("implied_vol", "")` or blank.

The absence of those pass-through fields should not block Stage 3 valuation.

---

## 16. Sort order

Stage 3 output should be deterministic.

Sort by:

1. Stage 2 tier order:
   - Diamond
   - Strong
   - Standard
   - Watch
2. `stage2_score` descending within tier
3. `symbol` alphabetically as tiebreaker

Suggested key:

```python
TIER_ORDER = {
    "Diamond": 0,
    "Strong": 1,
    "Standard": 2,
    "Watch": 3,
    "Eliminated": 4,
    "": 5,
}
```

---

## 17. Audit JSONL requirements

The JSONL audit file should include these event types:

### `stage3_run_start`

Should include:

- timestamp
- input CSV
- output CSV
- total input rows
- total eligible rows
- tiers requested
- min verdict threshold
- workers
- offline/input-only flag if supported

### `stage3_symbol_result`

One per processed symbol.

Should include:

- timestamp
- symbol
- stage2 tier
- stage2 score
- stage3 verdict
- stage3 category
- weighted fair value
- MOS threshold
- current price
- undervaluation pct
- QC fail reason, if any
- runtime ms

### `stage3_cascade_decision` or equivalent detail

Recommended, even if not explicitly required, because the auditor asked for clear cascade communication.

Should include after each tier:

- tier just completed
- symbols processed in tier
- cumulative symbols processed
- cumulative actionable count
- threshold
- continue/stop decision
- reason

### `stage3_run_complete`

Should include:

- timestamp
- tiers consumed
- cascade stopped early true/false
- symbols processed
- verdict counts
- actionable count
- runtime seconds
- output CSV path
- log path
- audit JSONL path

---

## 18. Human-readable run log requirements

The `.log` file should be suitable for GitHub/auditor review without needing to parse JSON.

It should include:

- run start timestamp
- input/output paths
- tier request
- worker count
- min-verdict threshold
- eligible row count
- per-symbol progress lines
- stage3 verdict per symbol
- category per symbol
- current price / MOS threshold / weighted FV where available
- QC fail reason where applicable
- cascade decisions after each tier
- final verdict distribution
- final actionable count
- run duration

Progress line example:

```text
[  3/6  50.0%] PCT stage2_tier=Diamond stage3_verdict=QC FAIL category= reason="zero or missing revenue"
```

---

## 19. Regression tests required before live run

Create:

```text
tests/test_stage3_runner.py
```

Minimum tests from the build brief:

1. `test_tier_cascade_stops_early`
   - Mock enough Diamond-tier `DIAMOND`/`ENTRY` results to meet threshold.
   - Assert Strong/Standard/Watch are not processed.

2. `test_tier_cascade_continues`
   - Mock too few Diamond actionable verdicts.
   - Assert Strong tier is processed.

3. `test_failed_analysis_isolation`
   - Mock one symbol raising an exception.
   - Assert output includes one `QC FAIL` row.
   - Assert remaining symbols still process.

4. `test_output_sort_order`
   - Given mixed-tier rows, assert output sorts Diamond first, then score descending, then symbol.

5. `test_stage2_kills_propagated`
   - Assert Stage 2 kill text from CSV becomes `analysis.stage2_kills` before `summary_verdict()`.
   - This test must cover the current live CSV alias `stage2_bad_text` as well as future `stage2_kills` if alias support is added.

### Additional tests I recommend

6. `test_current_stage2_column_aliases_are_supported`
   - Input row has `hp_tier`, `stage2_bad_text`, `stage2_weak_text`.
   - Assert runner interprets them as tier/kills/flags.

7. `test_min_verdicts_zero_processes_all_requested_tiers`
   - Assert cascade disabled behavior.

8. `test_stage3_analysis_none_becomes_qc_fail_row`
   - Mock `stage3_analysis()` returning `None`.
   - Assert output row is `QC FAIL` with clear reason.

9. `test_eliminated_stage2_rows_are_skipped`
   - Input includes an `Eliminated` row.
   - Assert it is not fetched/processed.

10. `test_audit_jsonl_contains_start_symbol_and_complete_events`
   - Assert JSONL event coverage is complete.

These extra tests directly guard the schema mismatch and run-audit requirements we found during review.

---

## 20. Offline mode expectations

The brief proposes:

```text
--offline-input-only
```

This should be used only for contract testing.

Expected behavior:

- Do not fetch fresh Finviz data.
- Do not fetch SEC data.
- Use Stage 2 price column only if needed for shape testing.
- Most/all valuation results may become `QC FAIL` because SEC data is unavailable.
- Log this explicitly so offline mode is never confused with live production validation.

Suggested log warning:

```text
offline_input_only=true: live Finviz and SEC fetches skipped; output validates CSV/log/audit contract only and is not a production Stage 3 valuation.
```

---

## 21. SEC data expectations

SEC companyfacts API is the intended fundamental spine.

Expected endpoint family:

```text
https://data.sec.gov/api/xbrl/companyfacts/{cik}.json
```

Important notes from the brief:

- Free, no API key required.
- Informal safe rate: about 10 requests/second, but Stage 3 should remain conservative.
- `--workers 2` is appropriate.
- Small caps and recent IPOs may not have complete coverage.
- SEC data can be stale until filings are updated.

The first Diamond-tier set from live Stage 2 is expected to include:

- MARA
- CLSK
- PCT
- QUBT
- USAR
- UUUU

The brief notes:

- All are public companies with SEC filings.
- Most/all may be Category B.
- MARA and CLSK are Bitcoin miners and may show volatile revenue economics.
- QUBT and PCT may QC-fail if revenue is zero/missing.

If QUBT or PCT come back `QC FAIL` due to zero or missing revenue, that should be documented, not treated as a runner bug.

---

## 22. Stage 3 output framing requirements for user-facing reports

When Stage 3 results are presented to Jonathan or downstream review docs, the output should clearly include:

- category,
- valuation method,
- bear / realistic / bull fair values,
- probability-weighted fair value,
- margin-of-safety threshold,
- current price,
- explicit final call: `DIAMOND`, `ENTRY`, `NO ENTRY`, or `QC FAIL`.

If current price is materially above MOS threshold, state `NO ENTRY` plainly even if Stage 1 and Stage 2 both passed.

Do not leave the user to infer the decision from valuation numbers alone.

---

## 23. QC guardrails to preserve

Stage 3 must preserve existing QC discipline:

### Share denominator sanity

Before trusting per-share fair value:

- compare implied market cap against current price × shares outstanding,
- avoid stale SEC share denominators,
- if per-share values look absurd relative to known market cap, fail QC rather than emitting misleading valuation.

### Zero / missing revenue

If revenue is zero or missing:

- do not divide by revenue,
- do not emit a misleading DCF,
- return `QC FAIL` with a clear reason.

### OCF vs SBC disclosure

For names with positive OCF but high SBC, later report generation should explicitly say if OCF is SBC-funded and show economic cash burn after backing out SBC.

The current runner build may not yet add full SBC extraction, but it should not block future extension and should preserve key facts where available.

### Operational watch / kill signals

Watch/kill signals should be company-specific and time-anchored where possible. Generic signals are acceptable only as placeholders until company-specific Stage 3 reporting is expanded.

---

## 24. What Stage 3 must not build

Do not add:

- strike selection,
- DTE analysis,
- premium yield calculation,
- earnings-date clearance,
- portfolio or position awareness,
- final trade recommendation,
- AI trade confirmation.

Those are downstream trade-construction / Stage 4 concerns.

If implementation starts computing options yield or selecting strikes, it has left Stage 3 scope.

---

## 25. Acceptance criteria before saying Stage 3 runner is ready

A Stage 3 build is ready for first live validation when:

1. `stages/stage3/code/run_stage3.py` exists.
2. It can run from repo root via `python -m stages.stage3.code.run_stage3 ...`.
3. It supports the current live Stage 2 schema aliases.
4. It skips Stage 2 `Eliminated` rows.
5. It processes requested tiers in correct cascade order.
6. It fetches fresh Finviz price in live mode.
7. It fetches SEC companyfacts in live mode.
8. It propagates Stage 2 kills/flags before `summary_verdict()`.
9. It converts symbol-level exceptions to `QC FAIL` rows.
10. It writes `Stage3_Report.csv`.
11. It writes a human-readable `.log`.
12. It writes a JSONL audit file with start/symbol/complete events.
13. It has regression tests for cascade, failure isolation, sort order, and kill propagation.
14. Full test suite passes.

A Stage 3 live run is valid when:

1. All eligible symbols in processed tiers have output rows.
2. No unhandled exception aborts the run.
3. JSONL event count matches symbols processed plus start/complete events.
4. Cascade log matches actual output rows.
5. `DIAMOND + ENTRY` count is credible and non-zero unless documented otherwise.
6. Any all-`QC FAIL` or all-`NO ENTRY` output is investigated before production clearance.

---

## 26. Recommended implementation sequence

1. Build `run_stage3.py` with small pure helper functions:
   - parse tier from row with aliases,
   - parse Stage 2 kills/flags with aliases,
   - parse floats/ints safely,
   - build `TickerAnalysis`,
   - convert Stage 3 dict to CSV row,
   - write audit events,
   - sort output rows.

2. Add `tests/test_stage3_runner.py` before live execution.

3. Run unit tests:

```bash
python -m pytest tests/test_stage3_runner.py
python -m pytest
```

4. Run a contract/offline smoke test if implemented.

5. Run Diamond-only live validation:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond \
  2>&1 | tee stages/stage3/audit_logs/stage3_live_validation_<timestamp>.operator.log
```

6. Verify artifacts:
   - report row count equals processed symbol count,
   - JSONL has start/result/complete events,
   - log clearly explains cascade result,
   - no Stage 2 killed names incorrectly become `DIAMOND`,
   - QC failures are reasoned.

7. Commit and push implementation + test + validation artifacts for Senior Dev / Code Auditor review.

---

## 27. Questions / requested confirmation

I have one implementation recommendation rather than a blocking question:

**Recommendation:** implement Stage 3 schema aliases now rather than patching Stage 2 output columns first.

Reason:

- The current Stage 2 live output has already been audited and published.
- Stage 3 can safely normalize input columns at its boundary.
- Alias support protects both current and future Stage 2 naming conventions.

Proposed alias map:

```text
stage2_tier   = row["stage2_tier"] if present else row["hp_tier"]
stage2_kills  = row["stage2_kills"] if present else row["stage2_bad_text"]
stage2_flags  = row["stage2_flags"] if present else row["stage2_weak_text"]
```

Unless Senior Dev or Code Auditor objects, this is the safest implementation path.

---

## 28. Final readiness assessment

Stage 3 is ready for implementation with the above safeguards.

The highest-risk issue is not the valuation engine; it is reconstructing the correct state from `Stage2_Report.csv` before calling `summary_verdict()`. Specifically, `stage2_kills` must be populated from the current Stage 2 `stage2_bad_text` field or a future `stage2_kills` field.

If that is handled and tested, the rest of the runner is straightforward pipeline work modeled after Stage 2.
