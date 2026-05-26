# Stage 3 self-heal handoff — 20260526T032041Z_MARA_PCT_QUBT_PLUS42

## Scope
- Report inspected: `/home/hermes/market-funnel/stages/stage3/output/Stage3_Report.csv`
- Affected symbols (45): MARA, PCT, QUBT, USAR, UUUU, APLD, GLXY, QBTS, ASST, IREN, RGTI, RIOT, RLAY, RUN, UEC, WULF, CIFR, CSIQ, IONQ, KSS, PL, SMCI, VG, VSCO, AMPX, FIG, INFQ, JOBY, LUNR, PGY, PUMP, RBRK, SEDG, SMR, VIAV, WOLF, AEVA, FLNC, LWLG, OUST, VOYG, VSH, WYFI, YSS, HIMX
- Production Stage 3 files were intentionally left unchanged. This bundle is review-only until Jonathan promotes it.

## Patch bundle
- trigger_id: `20260526T032041Z_MARA_PCT_QUBT_PLUS42`
- OG path: `stages/stage3/code/patches/20260526T032041Z_MARA_PCT_QUBT_PLUS42/original/run_stage3__og_20260526T032041Z_MARA_PCT_QUBT_PLUS42.py`
- Patched path: `stages/stage3/code/patches/20260526T032041Z_MARA_PCT_QUBT_PLUS42/patched/run_stage3__patched_20260526T032041Z_MARA_PCT_QUBT_PLUS42.py`
- Regression test: `tests/test_stage3_patch_bundle_20260526T032041Z.py`

## Root cause
The confirmed software gap is in the target-alignment guard, not in the raw valuation math: `run_stage3._target_alignment()` treated every >50% FV-vs-target gap as `software_patch_required = TRUE`. A Stage 2 / Finviz target gap is useful review evidence, but it is not by itself proof of a source bug or denominator bug, and forcing Stage 3 FV toward target prices would violate the valuation contract.

## Classification summary
- MODEL_FAMILY_MISSING: 23
- DATA_PROVIDER_ISSUE: 12
- NO_PATCH_SAFE: 7
- TARGET_OUTLIER: 3
- Original software_patch_required TRUE count: 45
- Patched simulated software_patch_required TRUE count: 0
- Full per-symbol CSV: `stages/stage3/audit_logs/stage3_self_heal_classification_20260526T032041Z_MARA_PCT_QUBT_PLUS42.csv`

## Per-symbol classification
- DATA_PROVIDER_ISSUE: GLXY, ASST, IREN, KSS, VG, FIG, INFQ, LUNR, PGY, RBRK, FLNC, VOYG
- MODEL_FAMILY_MISSING: MARA, PCT, QUBT, USAR, APLD, QBTS, RGTI, RIOT, RUN, UEC, WULF, CIFR, IONQ, VSCO, AMPX, JOBY, PUMP, SMR, WOLF, AEVA, OUST, WYFI, YSS
- NO_PATCH_SAFE: CSIQ, PL, SMCI, SEDG, VIAV, VSH, HIMX
- TARGET_OUTLIER: UUUU, RLAY, LWLG

## Verification
- Focused regression command passed: `pytest tests/test_stage3_runner.py tests/test_stage3_self_heal.py tests/test_screener.py tests/test_stage3_patch_bundle_20260526T032041Z.py -q`
- Result: `39 passed, 3 subtests passed`
- JSONL verification: `stages/stage3/audit_logs/stage3_self_heal_verification_20260526T032041Z_MARA_PCT_QUBT_PLUS42.jsonl`

## Human review / promotion note
The patched runner does not change fair values and does not declare these tickers investable. It keeps `SEVERE_MISALIGNMENT` visible but de-escalates `software_patch_required` when the only evidence is an external target gap. Names classified as `MODEL_FAMILY_MISSING` still need human/model-family review before their Stage 3 FV should be trusted. Names classified as `DATA_PROVIDER_ISSUE` need source/share-denominator review. Names classified as `TARGET_OUTLIER` need target-source review.
