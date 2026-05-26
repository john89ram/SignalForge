# Stage 3 Verdict

**Last updated (UTC):** 2026-05-26T03:26:04Z

## Runner build status

The canonical Stage 3 runner has been implemented at:

```text
stages/stage3/code/run_stage3.py
```

It consumes:

```text
stages/stage2/output/Stage2_Report.csv
```

and writes:

```text
stages/stage3/output/Stage3_Report.csv
```

with human-readable and JSONL audit logs under:

```text
stages/stage3/audit_logs/
```

## Current realignment status

`run_stage3.py` is mechanically healthy, but `Stage3_Report.csv` should currently be treated as a **mechanical baseline valuation screen**, not as the final user-facing Stage 3 fair-value report for every business model.

The user flagged implausibly low weighted fair values for familiar names such as IONQ and MARA. Review confirmed real source/model issues and produced this audit note:

```text
stages/stage3/audit_logs/stage3_price_fair_value_realign_20260526T021614Z.md
```

## Fixes implemented after the price/fair-value review

`screener.py` remediation now includes:

- Revenue tag selection considers all annual revenue tags, picks the most recent annual tag, and uses the broadest/largest tag when multiple current-year annual tags exist. This fixes MARA being valued from a narrow revenue tag instead of total `Revenues`.
- Flow facts (`NetIncomeLoss`, `OperatingIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`) prefer annual rows so annual revenue is not mixed with a latest-quarter flow figure.
- Post-valuation market-cap comparison no longer creates `QC FAIL`; share sanity belongs in the direct SEC-shares vs market-cap-implied-shares check before valuation. A fair value above market cap is a valuation signal, not a denominator failure.

Validation command:

```bash
PYTHONPATH=/home/hermes/market-funnel pytest -q tests/test_screener.py tests/test_stage3_runner.py
```

Result:

```text
30 passed, 3 subtests passed
```

## Latest Stage 3 full regeneration and self-heal trigger

Command:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 0 \
  --tiers Diamond,Strong,Standard,Watch
```

Operator tee log:

```text
stages/stage3/audit_logs/stage3_operator_full_run_20260526T031807Z.log
```

Runner artifacts:

```text
stages/stage3/output/Stage3_Report.csv
stages/stage3/audit_logs/stage3_run_20260526T031807Z.log
stages/stage3/audit_logs/stage3_run_20260526T031807Z.jsonl
```

Processed tiers:

```text
Diamond, Strong, Standard, Watch
```

Rows processed:

```text
65
```

Verdict count:

```json
{"NO ENTRY": 47, "DIAMOND": 1, "QC FAIL": 7, "ENTRY": 10}
```

Actionable mechanical outputs:

```text
DIAMOND + ENTRY count: 11
```

Patch-required target-alignment flags:

```text
software_patch_required_count=45
```

Flagged symbols:

```text
MARA, PCT, QUBT, USAR, UUUU, APLD, GLXY, QBTS, ASST, IREN, RGTI, RIOT, RLAY, RUN, UEC, WULF, CIFR, CSIQ, IONQ, KSS, PL, SMCI, VG, VSCO, AMPX, FIG, INFQ, JOBY, LUNR, PGY, PUMP, RBRK, SEDG, SMR, VIAV, WOLF, AEVA, FLNC, LWLG, OUST, VOYG, VSH, WYFI, YSS, HIMX
```

Option A self-heal command:

```bash
python -u stages/stage3/code/stage3_self_heal.py \
  --report-csv stages/stage3/output/Stage3_Report.csv
```

Self-heal artifacts:

```text
stages/stage3/audit_logs/stage3_operator_self_heal_20260526T031923Z.log
stages/stage3/audit_logs/stage3_self_heal_20260526T031923Z.log
stages/stage3/audit_logs/stage3_self_heal_20260526T031923Z.jsonl
stages/stage3/audit_logs/stage3_self_heal_prompt_20260526T031923Z.md
```

Self-heal result:

```text
Hermes invoked: true
Return code: 0
Runtime: 400.443 seconds
```

The nested remediation agent created and pushed a non-overwrite patch bundle instead of changing production Stage 3 code:

```text
trigger_id=20260526T032041Z_MARA_PCT_QUBT_PLUS42
commit=5aaecb1 fix(stage3): bundle self-heal target guard remediation
```

Patch bundle paths:

```text
stages/stage3/code/patches/20260526T032041Z_MARA_PCT_QUBT_PLUS42/original/run_stage3__og_20260526T032041Z_MARA_PCT_QUBT_PLUS42.py
stages/stage3/code/patches/20260526T032041Z_MARA_PCT_QUBT_PLUS42/patched/run_stage3__patched_20260526T032041Z_MARA_PCT_QUBT_PLUS42.py
```

Nested remediation classification summary:

```text
MODEL_FAMILY_MISSING: 23
DATA_PROVIDER_ISSUE: 12
NO_PATCH_SAFE: 7
TARGET_OUTLIER: 3
SOURCE_BUG: 0
SHARE_DENOMINATOR_BUG: 0
```

The patch bundle changes target-alignment guard semantics in the review copy only: severe gaps remain visible, but `software_patch_required = TRUE` is reserved for confirmed patchable defects instead of every >50% target gap. Production `stages/stage3/code/run_stage3.py` was not promoted.

## Current decision

**Runner mechanics:** GREEN  
**Source alignment fixes:** PARTIAL GREEN  
**Fair-value target guard:** GREEN  
**Generic DCF baseline:** USABLE FOR TRIAGE  
**Final fair-value methodology:** NOT FULLY REALIGNED

The generic Stage 3 DCF now has better source alignment, but it is still not sufficient as the sole fair-value engine for all names. Stage 3 needs model-family routing before final user-facing fair values should be trusted for:

- crypto miners / BTC-NAV-sensitive names such as MARA, RIOT, CLSK, WULF, IREN,
- deep-tech / milestone names such as IONQ, RGTI, QBTS, QUBT,
- HIMS, which needs the HIMS-specific Category A paradox / patent-risk overlay,
- other names where Stage 2 `one_yr_target` materially diverges from mechanical Stage 3 FV.

Next required engineering work: route tickers to model families instead of forcing every name through the same generic FCF DCF. `one_yr_target`, Finviz target, and target-vs-FV divergence flags are now present in Stage 3 output and logs; rows with `software_patch_required = TRUE` should be treated as engineering/model-source remediation candidates before trusting the mechanical fair value.
