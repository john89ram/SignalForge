# Stage 3 screener.py remediation handoff

**Date (UTC):** 2026-05-25T21:26:51Z  
**Author:** Hermes  
**Scope:** BUG-1 SEC revenue tag fallback + BUG-2 directional share sanity check  
**Status:** IMPLEMENTED / TESTED / LIVE VALIDATED

---

## Summary

Implemented the auditor-cleared `screener.py` remediation under TDD.

The original Diamond validation produced 6/6 `QC FAIL` rows. After the remediation, the Diamond tier now produces real valuation outputs for all six symbols:

```json
{"NO ENTRY": 6}
```

Because Diamond produced zero actionable `DIAMOND + ENTRY` names, the validation run cascaded into Strong as instructed by the audit clearance. Final post-fix cascade output:

```json
{"NO ENTRY": 16, "QC FAIL": 5}
```

No actionable entries were found in Diamond or Strong.

---

## Code changes

### BUG-1 — SEC revenue tag fallback

Patched `load_sec_companyfacts()` to support priority/fallback extraction across:

1. `RevenueFromContractWithCustomerExcludingAssessedTax`
2. `RevenueFromContractWithCustomerIncludingAssessedTax`
3. `Revenues`
4. `SalesRevenueNet`

Also addressed the auditor watch item: when selecting revenue rows, the loader now prefers annual facts (`fp == "FY"` or annual forms such as `10-K`, `20-F`, `40-F`) over a quarterly-only hit from an earlier tag. If no annual revenue rows are available from any fallback tag, it falls back to the first non-empty tag.

### BUG-2 — directional share sanity check

Patched both Stage 3 share sanity check locations so the QC fail only trips when model-implied market cap is materially **above** quoted market cap:

```text
(implied_mktcap - quoted_market_cap) / quoted_market_cap > 20%
```

A low DCF-implied value is now treated as a valid overvaluation / `NO ENTRY` result, not as a denominator QC failure.

---

## Tests added

Added regression coverage in `tests/test_screener.py` for:

- revenue fallback tags: `Revenues`, `SalesRevenueNet`, and `RevenueFromContractWithCustomerIncludingAssessedTax`
- annual revenue preference over a quarterly-only tag hit
- low model-implied market cap does **not** produce share-denominator `QC FAIL`
- high model-implied market cap still produces share-denominator `QC FAIL`

---

## Verification

Targeted checks:

```text
pytest tests/test_screener.py tests/test_stage3_runner.py -q
28 passed, 3 subtests passed in 0.14s
```

Full suite:

```text
pytest -q
64 passed, 3 subtests passed in 0.44s
```

Live validation command:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong
```

Live validation artifacts:

```text
stages/stage3/output/Stage3_Report.csv
stages/stage3/audit_logs/stage3_run_20260525T212651Z.log
stages/stage3/audit_logs/stage3_run_20260525T212651Z.jsonl
stages/stage3/audit_logs/stage3_operator_screener_fix_cascade_20260525T212651Z.log
```

JSONL audit event coverage:

```json
{
  "stage3_run_start": 1,
  "stage3_symbol_result": 21,
  "stage3_cascade_decision": 2,
  "stage3_run_complete": 1
}
```

---

## Post-fix results

### Diamond tier

All six Diamond names now produce real valuation outputs instead of source/QC failures:

```text
MARA  NO ENTRY  Category B
CLSK  NO ENTRY  Category B
PCT   NO ENTRY  Category B
QUBT  NO ENTRY  Category B
USAR  NO ENTRY  Category B
UUUU  NO ENTRY  Category A
```

Diamond verdict count:

```json
{"NO ENTRY": 6}
```

### Strong tier cascade

Strong was processed because Diamond produced 0 actionable entries versus the threshold of 5.

Strong outcomes:

```json
{"NO ENTRY": 10, "QC FAIL": 5}
```

Strong `QC FAIL` rows:

```text
BTDR  SEC data unavailable or no live price
PATH  share denominator sanity failed: implied $7.29B vs known $5.69B (28.1%)
RUN   share denominator sanity failed: implied $14.72B vs known $3.49B (321.6%)
SOC   zero or missing revenue
UEC   zero or missing revenue
```

The remaining share-denominator failures are directionally valid: the model-implied market caps are materially above quoted market caps.

---

## Decision

**Runner:** GREEN  
**BUG-1:** Fixed for tested fallback tags and annual preference  
**BUG-2:** Fixed for low-DCF false QC while preserving high-implied denominator guard  
**Diamond output:** GREEN as valuation output, but **NO ENTRY** for all six names  
**Strong cascade:** Completed; no actionable entries found

The post-fix result is a valid sieve outcome, not a runner/source failure.
