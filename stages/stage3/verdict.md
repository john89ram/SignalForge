# Stage 3 Verdict

**Last updated (UTC):** 2026-05-26T02:28:30Z

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

## Latest Stage 3 regeneration

Command:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong
```

Artifacts:

```text
stages/stage3/output/Stage3_Report.csv
stages/stage3/audit_logs/stage3_run_20260526T022830Z.log
stages/stage3/audit_logs/stage3_run_20260526T022830Z.jsonl
stages/stage3/audit_logs/stage3_operator_fv_alignment_20260526T022829Z.log
stages/stage3/audit_logs/stage3_fair_value_target_alignment_guard_20260526T022830Z.md
```

Processed tiers:

```text
Diamond, Strong
```

Rows processed:

```text
21
```

Verdict count:

```json
{"NO ENTRY": 17, "DIAMOND": 1, "QC FAIL": 2, "ENTRY": 1}
```

Actionable mechanical outputs surfaced:

```text
CLSK  DIAMOND  Category A  FV 21.10  MOS 16.88  Price 15.97
PATH  ENTRY    Category A  FV 14.00  MOS 11.20  Price 10.93
```

Diamond symbols processed:

```text
MARA, CLSK, PCT, QUBT, USAR, UUUU
```

Diamond verdict count:

```json
{"NO ENTRY": 5, "DIAMOND": 1}
```

Strong was processed because Diamond produced 1 actionable `DIAMOND + ENTRY` name versus the threshold of 5.

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
