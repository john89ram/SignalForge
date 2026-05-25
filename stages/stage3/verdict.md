# Stage 3 Verdict

**Last updated (UTC):** 2026-05-25T21:26:51Z

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

## Post-remediation validation

`screener.py` BUG-1 and BUG-2 are now remediated:

- SEC revenue extraction supports fallback tags and prefers annual rows when available.
- Stage 3 share sanity is directional: low DCF-implied market cap is a valid overvaluation result, while high model-implied market cap still trips denominator QC.

Validation command:

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
stages/stage3/audit_logs/stage3_run_20260525T212651Z.log
stages/stage3/audit_logs/stage3_run_20260525T212651Z.jsonl
stages/stage3/audit_logs/stage3_operator_screener_fix_cascade_20260525T212651Z.log
stages/stage3/audit_logs/stage3_screener_fix_handoff_20260525T212651Z.md
```

## Latest results

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
{"NO ENTRY": 16, "QC FAIL": 5}
```

Diamond symbols:

```text
MARA, CLSK, PCT, QUBT, USAR, UUUU
```

Diamond verdict count:

```json
{"NO ENTRY": 6}
```

Strong was processed because Diamond produced 0 actionable `DIAMOND + ENTRY` names versus the threshold of 5.

## Current decision

**Runner mechanics:** GREEN  
**screener.py remediation:** GREEN  
**Valuation output:** GREEN, with no actionable entries found in Diamond or Strong

The latest output is a valid sieve result: Diamond no longer source/QC-fails, but none of the tested Diamond or Strong names trade below the Stage 3 margin-of-safety threshold.
