# Stage 3 Option A self-heal build handoff — 20260526T030315Z

## What changed

- Added `stages/stage3/code/stage3_self_heal.py`.
- The script reads `stages/stage3/output/Stage3_Report.csv` and filters rows where `software_patch_required` is truthy.
- If patch-required rows exist, it builds a compact remediation prompt and invokes:

```bash
hermes chat -q "<prompt>"
```

- It writes human-readable and JSONL audit logs under `stages/stage3/audit_logs/`.
- It supports `--dry-run` so we can inspect the prompt and logs without spawning a nested Hermes remediation run.
- It supports `--hermes-bin` so the runner can use another Hermes executable/path if needed.
- Updated Stage 3 run completion JSONL/log summary to include:
  - `software_patch_required_count`
  - `software_patch_required_symbols`

## Safety guardrails in prompt

The generated Hermes prompt tells the remediation agent to:

- inspect data and code before changing anything;
- classify each flagged symbol as `SOURCE_BUG`, `MODEL_FAMILY_MISSING`, `DATA_PROVIDER_ISSUE`, `SHARE_DENOMINATOR_BUG`, `TARGET_OUTLIER`, or `NO_PATCH_SAFE`;
- patch only if warranted by a confirmed software/model gap;
- avoid forcing valuations to match external targets;
- add/update regression tests for any code change;
- rerun enough Stage 3 verification to prove the flags changed or are documented as non-code issues;
- write audit handoff notes before reporting back.

## Test evidence

```bash
python -m pytest tests/test_stage3_runner.py tests/test_stage3_self_heal.py -q -o 'addopts='
# 16 passed in 0.15s
```

## Smoke evidence

Dry-run command:

```bash
python stages/stage3/code/stage3_self_heal.py \
  --report-csv stages/stage3/output/Stage3_Report.csv \
  --dry-run
```

Dry-run result:

- Patch-required rows: 16
- Symbols: `MARA, PCT, QUBT, USAR, UUUU, APLD, GLXY, QBTS, ASST, IREN, RGTI, RIOT, RLAY, RUN, UEC, WULF`
- Hermes invoked: `False` because this was a dry run
- Prompt artifact: `stages/stage3/audit_logs/stage3_self_heal_prompt_20260526T030315Z.md`

## Operator notes

To run live Option A after a Stage 3 report exists:

```bash
python stages/stage3/code/stage3_self_heal.py \
  --report-csv stages/stage3/output/Stage3_Report.csv
```

To inspect without invoking Hermes:

```bash
python stages/stage3/code/stage3_self_heal.py \
  --report-csv stages/stage3/output/Stage3_Report.csv \
  --dry-run
```
