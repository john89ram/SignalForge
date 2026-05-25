# Stage 3 Verdict

**Last updated (UTC):** 2026-05-25T20:36:19Z

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

## First Diamond validation run

Command shape:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond
```

Processed Diamond symbols:

```text
MARA, CLSK, PCT, QUBT, USAR, UUUU
```

Verdict count:

```json
{"QC FAIL": 6}
```

## Current decision

**Runner mechanics:** GREEN  
**Valuation output:** NOT GREEN YET

The runner passed regression tests and produced the expected CSV/log/JSONL artifacts. The first live Diamond run surfaced Stage 3 valuation-source issues in the existing DCF/source path: every Diamond name returned `QC FAIL`.

This should be treated as a follow-up valuation-source remediation task, not as a runner crash.
