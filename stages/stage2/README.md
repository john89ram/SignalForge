# Stage 2 — The Sieve

Stage 2 consumes the completed Stage 1 pass artifact and separates mechanically eligible premium names into Stage 3 priorities.

## Input handoff

Canonical input:

```text
stages/stage2/input/Stage1_PASS.csv
```

Current checked handoff: **71 rows** from Stage 1 / Step 5 after options-liquidity enrichment.

Stage 1 remains the mechanical truth. Stage 2 must not mutate or reinterpret `stage1_pass`; it writes separate Stage 2 verdict, HP, tier, and `eligible_for_stage3` fields.

## HP framework

Starting HP: **10**

Each test can apply:

- `PASS`: 0 HP lost
- `WEAK`: 1 HP lost
- `BAD`: 2 HP lost
- `SKIP`: 0 HP lost, used only when a data field is unavailable

Priority tiers:

- `9–10`: Diamond — full Stage 3, strong position-sizing candidate
- `7–8`: Strong — full Stage 3, standard sizing
- `5–6`: Standard — Stage 3 with caution, reduced sizing
- `3–4`: Watch — light Stage 3 or observation only
- `0–2`: Eliminated — does not advance

## Seven tests

The former Binary Event / Operating Floor test was removed because it duplicated IV Spike Diagnosis once earnings were excluded as a kill signal.

Canonical tests, each implemented as its own class in `code/stage2_sieve.py`:

1. `IVSpikeDiagnosisTest`
2. `MemeStockTest`
3. `ChartPatternTest`
4. `NewsSentimentTest`
5. `AnalystConsensusTest`
6. `LiquidityTest`
7. `InstitutionalOwnershipTest`

## Running Stage 2

```bash
python -m stages.stage2.code.run_stage2 \
  stages/stage2/input/Stage1_PASS.csv \
  --output-csv stages/stage2/output/Stage2_Report.csv \
  --workers 2
```

For deterministic/no-network smoke runs from the Stage 1 CSV fields only:

```bash
python -m stages.stage2.code.run_stage2 \
  stages/stage2/input/Stage1_PASS.csv \
  --output-csv stages/stage2/output/Stage2_Report.csv \
  --offline-input-only
```

The offline mode is useful for CI and output-contract verification. Live-data fields not present in `Stage1_PASS.csv` are marked `SKIP` or neutral by their individual tests.

The legacy root script remains as a compatibility wrapper:

```bash
python stage2_report.py stages/stage2/input/Stage1_PASS.csv \
  --output-csv stages/stage2/output/Stage2_Report.csv
```

## Output and logs

Canonical output:

```text
stages/stage2/output/Stage2_Report.csv
```

Each run also writes:

```text
stages/stage2/audit_logs/stage2_run_<timestamp>.log
stages/stage2/audit_logs/stage2_run_<timestamp>.jsonl
```

The log records per-symbol progress. The JSONL audit row records row counts, tier distribution, verdict distribution, elapsed runtime, and input/output paths.
