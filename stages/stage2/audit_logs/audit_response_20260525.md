# SignalForge Stage 2 Audit Response

**Date:** 2026-05-25
**Source review:** `stages/stage2/audit_logs/audit_review_20260525.md`
**Response status:** blocking and documented medium items addressed in code/docs; live Stage 2 run still required for production clearance.

## Summary

The audit review was pulled from git and reviewed. The major logic blockers were valid. This response implements code fixes with regression tests, updates stale docs, and preserves compatibility where existing callers used the old Stage 1 Step 4 complete-output module name.

## Items addressed

### CRIT-1 — ChartPatternTest SMA comparisons

Status: **fixed**

Change:

- Added conversion from Finviz SMA percent deviation back to approximate absolute SMA reference price before comparing to current price.
- `SMA200 = -10` is now interpreted as price being 10% below the 200-day SMA and returns `BAD`.
- `SMA50 = -10` with price above the 200-day SMA now returns `WEAK`.

Regression test:

- `tests/test_stage2_sieve.py::test_chart_pattern_converts_finviz_sma_deviation_to_absolute_price`

### HIGH-1 / MED-3 — Offline run qualification

Status: **documented**

Change:

- `stages/stage2/README.md` now states that run `20260525T161635Z` validates runner mechanics, output shape, progress logging, and JSONL audit coverage only.
- `stages/stage2/verdict.md` now states that the first live run must still validate all seven tests against fetched data before production clearance.

### HIGH-2 — InstitutionalOwnershipTest insider selling ordering

Status: **fixed**

Change:

- Insider selling spike check now runs before the borderline 30–50% institutional ownership return.
- A ticker with 40% institutional ownership and `insider_trans <= -20` now returns `BAD`, not `WEAK`.

Regression test:

- `tests/test_stage2_sieve.py::test_institutional_ownership_flags_insider_selling_before_borderline_ownership`

### HIGH-3 — Dead `_stage2_add_test` function

Status: **removed**

Change:

- Deleted dormant `_stage2_add_test` from `screener.py` so old `KILL`/flat-HP semantics cannot be accidentally reconnected.
- `analyze_stage2()` remains the compatibility wrapper around the canonical `Stage2Sieve` implementation.

### HIGH-4 — Step 3 `_value_missing` treated zero as missing

Status: **fixed**

Change:

- `_value_missing()` now treats any parseable number as present.
- `barchart_iv_rank = 0` and `barchart_iv_percentile = 0` no longer trigger spurious repair retries.

Regression test:

- `tests/test_stage1_step3_barchart_enrichment.py::Stage1Step3BarchartEnrichmentTests::test_missing_fields_treats_zero_iv_rank_as_present`

### MED-1 — Stale project layout

Status: **updated**

Change:

- `docs/project-layout.md` now maps Stage 1 to the canonical `stages/stage1/code/step1..step5` pipeline and Stage 2 to `stages/stage2/code/stage2_sieve.py` / `run_stage2.py`.

### MED-2 — Stage 1 Step 4 vs Step 5 numbering conflict

Status: **resolved with compatibility wrapper**

Change:

- Canonical complete-output module is now `stages.stage1.code.step5_complete_stage1_output`.
- The old `stages.stage1.code.step4_complete_stage1_output` remains as a thin compatibility wrapper for older callers.
- Root README, Stage 1 README, Stage 1 code README, and tests now use Step 5 naming.

## Remaining tracked low items

Not blocking for Stage 2 production clearance, but still worth tracking:

- LOW-1: defensive Finviz volume parsing if `Volume` disappears and only `Rel Volume` remains.
- LOW-2: consider adding `tested_count` / `skipped_count` if `stage2_score` is used directly for Stage 3 prioritization.

## Verification

Full test suite:

```text
50 passed in 0.42s
```

Production clearance note:

Stage 2 is closer to live-run readiness, but production clearance should still wait for a live Stage 2 run that exercises news, price history, SMA/range, and institutional-ownership fields rather than `--offline-input-only`.
