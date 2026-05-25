# Stage 3 Runner Build Handoff

**Timestamp (UTC):** 2026-05-25T20:36:19Z  
**Author:** Hermes  
**Subject:** Stage 3 canonical runner implementation and first Diamond validation run  
**Implementation target:** `stages/stage3/code/run_stage3.py`  
**Input artifact:** `stages/stage2/output/Stage2_Report.csv`  
**Output artifact:** `stages/stage3/output/Stage3_Report.csv`

---

## Summary

Stage 3 runner build is implemented.

The new runner wraps the existing `screener.py` Stage 3 valuation engine. It does **not** rewrite the DCF engine. It consumes the canonical Stage 2 report, applies the tier cascade, reconstructs `TickerAnalysis`, calls `stage3_analysis()`, calls `summary_verdict()`, writes the Stage 3 CSV, and emits both human and JSONL audit logs.

The implementation follows the approved README Revision 3 guidance, including the constructor fix and defensive Stage 2 alias handling.

---

## Files added

```text
stages/stage3/__init__.py
stages/stage3/code/__init__.py
stages/stage3/code/run_stage3.py
tests/test_stage3_runner.py
```

Generated validation artifacts from the first Diamond run:

```text
stages/stage3/output/Stage3_Report.csv
stages/stage3/audit_logs/stage3_run_20260525T203505Z.log
stages/stage3/audit_logs/stage3_run_20260525T203505Z.jsonl
stages/stage3/audit_logs/stage3_operator_diamond_build_20260525T203505Z.log
```

---

## Implemented runner behavior

### Input handling

- Reads `Stage2_Report.csv`.
- Supports current Stage 2 column names:
  - `hp_tier`
  - `stage2_bad_text`
  - `stage2_bad_count`
  - `stage2_weak_text`
  - `eligible_for_stage3`
- Supports alias names if future Stage 2 output renames them:
  - `stage2_tier`
  - `stage2_kills`
  - `stage2_flags`

### Eligibility guard

Rows are processed only when both conditions pass:

```text
hp_tier != Eliminated
eligible_for_stage3 is not false-like
```

### Tier cascade

Default cascade order:

```text
Diamond -> Strong -> Standard -> Watch
```

`--min-verdicts N` stops once cumulative `DIAMOND + ENTRY >= N`.

`--min-verdicts 0` disables early stopping and processes all requested tiers.

### TickerAnalysis reconstruction

The runner uses the corrected constructor:

```python
TickerAnalysis(
    symbol=symbol,
    quote=q,
    barchart=BarchartSnapshot(),
    options=OptionsSnapshot(),
)
```

This avoids the approved README Revision 2 constructor failure.

### Kill parsing

The runner preserves Stage 2 hard-kill count/detail before `summary_verdict()`:

- If `stage2_bad_count` exists, it is used as the count authority.
- If only text exists, parsed pipe-delimited kill text is trusted.
- If count exists but text is missing/mismatched, placeholder kills preserve the count so `summary_verdict()` cannot incorrectly upgrade a name to `DIAMOND`.

### Output CSV

Writes:

```text
stages/stage3/output/Stage3_Report.csv
```

with fields:

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

Sort order:

```text
stage2 tier order -> stage2_score descending -> symbol ascending
```

### Logging and audit

The runner writes:

- human-readable `.log`
- JSONL audit log
- operator-visible progress when not run with `--quiet`

JSONL event types:

```text
stage3_run_start
stage3_symbol_result
stage3_cascade_decision
stage3_run_complete
```

Run-start event includes input tier counts so stale/offline Stage 2 artifacts are visible immediately.

---

## Tests added

`tests/test_stage3_runner.py` includes 11 regression tests:

1. `test_tier_cascade_stops_early`
2. `test_tier_cascade_continues`
3. `test_failed_analysis_isolation`
4. `test_output_sort_order`
5. `test_stage2_kills_propagated`
6. `test_current_stage2_column_aliases_are_supported`
7. `test_stage2_kills_alias_without_bad_count_is_trusted`
8. `test_min_verdicts_zero_processes_all_requested_tiers`
9. `test_stage3_analysis_none_becomes_qc_fail_row`
10. `test_eliminated_stage2_rows_are_skipped`
11. `test_audit_jsonl_contains_all_event_types`

---

## Test results

Full test suite passed after implementation and after pulling README Revision 3:

```text
61 passed in 0.43s
```

Targeted Stage 3 runner test result:

```text
11 passed in 0.13s
```

---

## First Diamond validation command

Command used:

```bash
git pull --ff-only
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond \
  2>&1 | tee stages/stage3/audit_logs/stage3_operator_diamond_build_20260525T203505Z.log
```

---

## First Diamond validation result

The runner processed the 6 Diamond-tier names from the live Stage 2 artifact:

```text
MARA
CLSK
PCT
QUBT
USAR
UUUU
```

Output rows:

```text
6
```

Verdict counts:

```json
{
  "QC FAIL": 6
}
```

Audit event coverage:

```json
{
  "stage3_run_start": 1,
  "stage3_symbol_result": 6,
  "stage3_cascade_decision": 1,
  "stage3_run_complete": 1
}
```

Run-complete event:

```json
{
  "actionable_count": 0,
  "cascade_stopped_early": false,
  "event": "stage3_run_complete",
  "runtime_seconds": 5.446,
  "symbols_processed": 6,
  "tiers_consumed": ["Diamond"],
  "verdicts": {"QC FAIL": 6}
}
```

---

## Important validation finding

The runner mechanics are working, but the first Diamond live validation surfaced Stage 3 valuation-engine/source limitations: all six Diamond names returned `QC FAIL`.

Observed reasons:

```text
CLSK: SEC data unavailable or no live price
PCT:  SEC data unavailable or no live price
QUBT: SEC data unavailable or no live price
USAR: SEC data unavailable or no live price
MARA: share denominator sanity failed: implied $0.51B vs known $5.27B (90.4%)
UUUU: share denominator sanity failed: implied $0.25B vs known $4.51B (94.4%)
```

This is not a runner crash. It is a useful validation result showing that the existing Stage 3 DCF/source extraction path needs follow-up before Stage 3 can produce actionable valuation decisions for this Diamond set.

Likely follow-up areas:

1. SEC revenue tag coverage: some Diamond symbols have companyfacts loaded but no revenue under the current extracted revenue tag family.
2. Annual-vs-quarterly source alignment: MARA and UUUU appear to hit share-denominator sanity failures because the existing engine can mix a recent quarterly revenue value with annual/share/market-cap checks.
3. Stage 3 source-alignment checkpoint from prior methodology notes should be applied before trusting valuation output.

Per build instruction, I did not rewrite the DCF engine inside this runner implementation.

---

## Current status

### Runner build

**Green.** The Stage 3 runner is implemented, tested, and produces output/log/audit artifacts.

### First live Diamond valuation output

**Not valuation-green yet.** The output is intentionally preserved because it shows the next issue clearly: all Diamond names QC-failed inside the existing Stage 3 valuation/source path.

### Recommended next step

Ask Dev/Auditor to review the runner implementation and the first-run artifacts. If approved mechanically, the next development task should be Stage 3 valuation-source remediation, especially SEC revenue tag coverage and annual source alignment.
