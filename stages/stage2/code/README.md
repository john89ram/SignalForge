# Stage 2 code

Canonical Stage 2 implementation lives here.

## Files

- `stage2_sieve.py` — the seven-test HP framework. Each test is isolated in its own class with a `run(...)` method:
  - `IVSpikeDiagnosisTest`
  - `MemeStockTest`
  - `ChartPatternTest`
  - `NewsSentimentTest`
  - `AnalystConsensusTest`
  - `LiquidityTest`
  - `InstitutionalOwnershipTest`
- `run_stage2.py` — CLI/report runner that consumes `Stage1_PASS.csv`, writes `Stage2_Report.csv`, and emits audit logs. Supports `--offline-input-only` for deterministic output-contract smoke runs without network calls.

The root-level `stage2_report.py` file is now a backward-compatible wrapper around `run_stage2.py`.

## Design rule

Do not collapse the seven tests into one large function. Keep each test as a separate class/function so rule tuning, troubleshooting, and replacement stay isolated.
