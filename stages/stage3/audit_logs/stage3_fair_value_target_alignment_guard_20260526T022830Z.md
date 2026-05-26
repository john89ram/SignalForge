# Stage 3 fair-value target alignment guard

Timestamp: 2026-05-26T02:28:30Z

## Purpose

The Stage 3 runner now checks whether the mechanical Stage 3 weighted fair value is remotely close to the Stage 2 `one_yr_target` and the live Finviz analyst target. If the Stage 3 fair value is severely misaligned from every available positive target benchmark, the row is marked as requiring a software patch before the fair value should be trusted.

## Rule implemented

For each Stage 3 result:

1. Read `stage2_one_yr_target` from the Stage 2 input row's `one_yr_target` column.
2. Read `finviz_target_price` from the live Finviz quote snapshot.
3. Compare `weighted_fair_value` against both available targets.
4. Use the closest available target as `target_benchmark_price` so a stale outlier target does not create a false positive.
5. If the absolute gap from the closest benchmark is greater than 50%, set:
   - `fair_value_target_alignment = SEVERE_MISALIGNMENT`
   - `software_patch_required = TRUE`
   - `fair_value_target_gap_detail` with the exact FV, closest benchmark, all target values, and patch warning.
6. If the gap is within 50%, set:
   - `fair_value_target_alignment = ALIGNED`
   - `software_patch_required = FALSE`
7. If Stage 3 FV or positive target benchmarks are unavailable, set:
   - `fair_value_target_alignment = NO_TARGET_CHECK`
   - `software_patch_required = FALSE`

## New Stage3_Report.csv fields

- `stage2_one_yr_target`
- `finviz_target_price`
- `target_benchmark_price`
- `fair_value_target_gap_pct`
- `fair_value_target_alignment`
- `software_patch_required`
- `fair_value_target_gap_detail`

## Logging changes

Every `symbol_result` line in the operator log now includes:

- Stage 3 FV
- Stage 2 target
- Finviz target
- FV/target alignment status
- FV/target gap percent
- software patch requirement flag

Every `stage3_symbol_result` JSONL audit event includes the same fields.

## Verification

Unit/regression tests:

```bash
PYTHONPATH=/home/hermes/market-funnel pytest -q tests/test_screener.py tests/test_stage3_runner.py
```

Result:

```text
32 passed, 3 subtests passed
```

Representative Stage 3 run:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong
```

Run artifacts:

- `stages/stage3/output/Stage3_Report.csv`
- `stages/stage3/audit_logs/stage3_run_20260526T022830Z.log`
- `stages/stage3/audit_logs/stage3_run_20260526T022830Z.jsonl`
- `stages/stage3/audit_logs/stage3_operator_fv_alignment_20260526T022829Z.log`

Verification summary:

- Rows processed: 21
- JSONL symbol events: 21
- Symbol events with `software_patch_required`: 21
- `software_patch_required = TRUE`: 16
- `fair_value_target_alignment = ALIGNED`: 3
- `QC FAIL`: 2

Flagged symbols:

```text
MARA, PCT, QUBT, USAR, UUUU, APLD, GLXY, QBTS, ASST, IREN, RGTI, RIOT, RLAY, RUN, UEC, WULF
```

Aligned examples:

- `CLSK`: FV $21.10 vs Stage 2 target $21.50 / Finviz target $20.21
- `FSLY`: FV $16.97 vs Stage 2 target $24.00 / Finviz target $25.20; within 50% guardrail but still NO ENTRY mechanically
- `PATH`: FV $14.00 vs Stage 2 target $13.00 / Finviz target $13.67

## Interpretation

This guard does not make analyst targets the valuation model. It is a sanity check. A severe mismatch means Stage 3 is likely using the wrong model family, bad source inputs, stale share data, or a missing domain-specific valuation path. The row should be treated as requiring an engineering/software patch before its mechanical fair value is trusted.
