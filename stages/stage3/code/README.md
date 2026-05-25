# Stage 3 — Build Specification for run_stage3.py

**Author:** Hermes Gatekeeper (Auditor)
**Date:** 2026-05-25
**Status:** Ready to build — all dependencies confirmed present in codebase

---

## Overview

Stage 3 needs a canonical batch runner: `stages/stage3/code/run_stage3.py`.
This mirrors the architecture of `stages/stage2/code/run_stage2.py` — read a CSV, process
symbols concurrently, write an output CSV, emit JSONL audit events.

The DCF engine already exists. Do not rewrite it. Your job is to build the pipeline
wrapper around it.

---

## What Already Exists — Do Not Rewrite

All of the following are production-ready in `screener.py`. Import them directly.

```python
from screener import (
    TickerAnalysis,
    QuoteSnapshot,
    SECFacts,
    load_sec_companyfacts,
    parse_finviz_quote,
    stage3_analysis,
    stage3_share_count,
    summary_verdict,
    HTTP,
)
```

- `stage3_analysis(analysis: TickerAnalysis) -> Optional[Dict[str, Any]]`
  The complete DCF engine. Handles Category A/B classification, 5-year FCF projection,
  scenario weighting, share QC, and the APLD bespoke model. Returns a dict or None.

- `summary_verdict(a: TickerAnalysis) -> str`
  Maps a TickerAnalysis to exactly one of: DIAMOND, ENTRY, NO ENTRY, QC FAIL.

- `load_sec_companyfacts(http: HTTP, symbol: str) -> Optional[SECFacts]`
  Fetches from https://data.sec.gov/api/xbrl/companyfacts/{cik}.json
  Free API. No authentication. Throttle to ~2 requests/second to be a good citizen.

- `parse_finviz_quote(html: str, symbol: str) -> QuoteSnapshot`
  Used to get a live price snapshot. Stage 3 needs a current price for the MOS comparison.

---

## Input Contract

**File:** `stages/stage2/output/Stage2_Report.csv`

Required columns from Stage 2 output (all present in current Stage2_Report.csv):

| Column | Used for |
|---|---|
| `symbol` | Ticker lookup |
| `stage2_tier` | Tier-cascade filtering |
| `stage2_score` | Output sort order within tier |
| `stage2_hp_left` | Pass-through to Stage 3 output |
| `stage2_verdict` | Pass-through (PASS / ELIMINATED) |
| `stage2_kills` | Used by summary_verdict() via analysis.stage2_kills |
| `stage2_flags` | Pass-through to Stage 3 output |

**Tier order for cascade processing:** Diamond -> Strong -> Standard -> Watch
Eliminated symbols are always skipped. Do not process them.

---

## Reconstructing TickerAnalysis from CSV

`stage3_analysis()` requires a `TickerAnalysis` object. You must reconstruct it from
the Stage 2 CSV row + fresh fetches. Minimum viable reconstruction:

```python
def _analysis_from_stage2_row(row: dict, http: HTTP) -> TickerAnalysis:
    symbol = row["symbol"].strip().upper()

    # Fresh price fetch — Stage 2 price may be hours old; MOS comparison needs today's price
    finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
    q = parse_finviz_quote(finviz_html, symbol)

    # Rebuild Stage 2 state so summary_verdict() works correctly
    analysis = TickerAnalysis(symbol=symbol, quote=q)
    analysis.stage1_pass = True  # Only eligible names reach Stage 3
    analysis.stage2_kills = [k.strip() for k in row.get("stage2_kills", "").split("|") if k.strip()]
    analysis.stage2_flags = [f.strip() for f in row.get("stage2_flags", "").split("|") if f.strip()]
    analysis.stage2_tier = row.get("stage2_tier", "")
    analysis.stage2_score = float(row.get("stage2_score", 0.0) or 0.0)
    analysis.stage2_hp_left = int(row.get("stage2_hp_left", 0) or 0)
    analysis.eligible_for_stage3 = True  # Guaranteed by tier filter above

    # SEC fetch — this is the primary data source for the DCF
    analysis.sec = load_sec_companyfacts(http, symbol)

    return analysis
```

---

## Cascade Logic

The runner supports tier-ordered cascade to avoid burning API calls on the full 65-name set
when the top tier alone yields enough actionable names.

**CLI argument:** `--min-verdicts N` (default: 5)
Minimum count of DIAMOND + ENTRY verdicts before cascade stops.

**Behavior:**
1. Process all Diamond-tier symbols from Stage 2 output
2. Count DIAMOND + ENTRY verdicts
3. If count >= --min-verdicts, stop. Do not process Strong, Standard, or Watch.
4. Otherwise, process Strong tier. Re-evaluate count.
5. Continue through Standard, then Watch, until threshold met or all tiers exhausted.
6. Log which tiers were consumed and why cascade continued/stopped.

**Important:** `--min-verdicts 0` disables the cascade and processes all eligible tiers.
This is useful for a full validation run. Default should be 5 for production use.

**Tier filter argument:** `--tiers Diamond,Strong,Standard,Watch` (default: all four)
Allows running a single tier in isolation for debugging.

---

## Concurrency

Use `concurrent.futures.ThreadPoolExecutor` with a configurable `--workers` argument.
Default: 2. Maximum recommended: 3 (SEC API is tolerant but Finviz is not).

The SEC fetch and Finviz fetch happen inside the worker thread per symbol.
Index-order output: collect all results, sort by tier order + stage2_score before writing CSV.

Error isolation: wrap each symbol in try/except. On exception, emit a QC FAIL result
with the exception message as the qc_fail_reason. Never let one symbol crash the run.

```python
def _failed_analysis(symbol: str, stage2_row: dict, reason: str) -> dict:
    """Return a QC FAIL row for output CSV when an exception occurs."""
    return {
        "symbol": symbol,
        "stage2_tier": stage2_row.get("stage2_tier", ""),
        "stage2_score": stage2_row.get("stage2_score", ""),
        "stage2_hp_left": stage2_row.get("stage2_hp_left", ""),
        "stage3_verdict": "QC FAIL",
        "stage3_category": "",
        "weighted_fair_value": "",
        "mos_threshold": "",
        "current_price": "",
        "undervaluation_pct": "",
        "qc_fail_reason": reason,
        "share_count_source": "",
        "share_qc_detail": "",
        "watch_signal": "",
        "kill_signal": "",
        "stage2_kills": stage2_row.get("stage2_kills", ""),
        "stage2_flags": stage2_row.get("stage2_flags", ""),
        "sector": stage2_row.get("sector", ""),
        "iv_rank": stage2_row.get("iv_rank", ""),
        "implied_vol": stage2_row.get("implied_vol", ""),
    }
```

---

## Output Contract — Stage3_Report.csv

Write to `stages/stage3/output/Stage3_Report.csv`.

| Column | Source | Notes |
|---|---|---|
| `symbol` | Stage 2 CSV | |
| `stage2_tier` | Stage 2 CSV | Diamond/Strong/Standard/Watch |
| `stage2_score` | Stage 2 CSV | 0.0-7.0 |
| `stage2_hp_left` | Stage 2 CSV | 0-10 |
| `stage3_verdict` | summary_verdict() | DIAMOND/ENTRY/NO ENTRY/QC FAIL |
| `stage3_category` | s3["category"] | A or B |
| `weighted_fair_value` | s3["weighted_fair_value"] | float or blank |
| `mos_threshold` | s3["mos_threshold"] | float or blank |
| `current_price` | s3["current_price"] | float |
| `undervaluation_pct` | s3["undervaluation_pct"] | positive = undervalued |
| `bear_value` | s3["bear"] | per-share bear scenario |
| `realistic_value` | s3["realistic"] | per-share realistic scenario |
| `bull_value` | s3["bull"] | per-share bull scenario |
| `qc_fail_reason` | s3["qc_fail_reason"] | blank unless QC FAIL |
| `share_count_source` | s3["share_count_source"] | "sec" or "market_cap_implied" |
| `share_qc_detail` | s3["share_qc_detail"] | blank unless QC mismatch |
| `watch_signal` | s3["watch_signal"] | text or blank |
| `kill_signal` | s3.get("kill_signal") | text or blank (APLD only) |
| `stage2_kills` | Stage 2 CSV | pass-through |
| `stage2_flags` | Stage 2 CSV | pass-through |
| `sector` | Stage 2 CSV | pass-through |
| `iv_rank` | Stage 2 CSV | pass-through |
| `implied_vol` | Stage 2 CSV | pass-through |

**Sort order:** Tier order (Diamond first, Watch last), then stage2_score descending within tier,
then symbol alphabetically as a tiebreaker.

**Tier sort key:**
```python
TIER_ORDER = {"Diamond": 0, "Strong": 1, "Standard": 2, "Watch": 3, "Eliminated": 4, "": 5}
```

---

## Audit Logging

Emit three types of JSONL events to `stages/stage3/audit_logs/stage3_run_<timestamp>.jsonl`:

**Run start:**
```json
{
  "event": "stage3_run_start",
  "timestamp": "2026-05-25T18:00:00Z",
  "input_csv": "stages/stage2/output/Stage2_Report.csv",
  "total_eligible": 65,
  "tiers_requested": ["Diamond", "Strong", "Standard", "Watch"],
  "min_verdicts": 5,
  "workers": 2
}
```

**Per-symbol result:**
```json
{
  "event": "stage3_symbol_result",
  "symbol": "MARA",
  "stage2_tier": "Diamond",
  "stage3_verdict": "ENTRY",
  "stage3_category": "B",
  "weighted_fair_value": 14.20,
  "mos_threshold": 7.10,
  "current_price": 16.45,
  "undervaluation_pct": -13.6,
  "qc_fail_reason": null,
  "runtime_ms": 1240
}
```

**Run complete:**
```json
{
  "event": "stage3_run_complete",
  "timestamp": "2026-05-25T18:05:00Z",
  "tiers_consumed": ["Diamond"],
  "cascade_stopped_early": true,
  "symbols_processed": 6,
  "verdicts": {"DIAMOND": 1, "ENTRY": 4, "NO ENTRY": 1, "QC FAIL": 0},
  "actionable_count": 5,
  "runtime_seconds": 48.2,
  "output_csv": "stages/stage3/output/Stage3_Report.csv"
}
```

Write a matching `.log` file with human-readable progress lines (same format as Stage 2 run log).

---

## CLI Interface

```
python -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong,Standard,Watch
```

| Argument | Default | Notes |
|---|---|---|
| `input_csv` | positional | Path to Stage2_Report.csv |
| `--output-csv` | auto-named | Default: stages/stage3/output/Stage3_Report.csv |
| `--workers` | 2 | ThreadPoolExecutor workers |
| `--min-verdicts` | 5 | Cascade stops when DIAMOND+ENTRY >= this |
| `--tiers` | all four | Comma-separated, ordered |
| `--offline-input-only` | False | Skip live fetches; use Stage 2 price column. For contract testing only. |

---

## Regression Tests

Write tests in `tests/test_stage3_runner.py`. Minimum required:

1. `test_tier_cascade_stops_early` — mock 3 DIAMOND+ENTRY verdicts from Diamond tier with min_verdicts=3; assert Strong tier is never processed.
2. `test_tier_cascade_continues` — mock 2 DIAMOND+ENTRY verdicts from Diamond tier with min_verdicts=5; assert Strong tier is processed.
3. `test_failed_analysis_isolation` — mock one symbol raising an exception; assert output contains QC FAIL row and remaining symbols processed correctly.
4. `test_output_sort_order` — given mixed-tier results, assert output CSV is sorted Diamond first, then by stage2_score descending.
5. `test_stage2_kills_propagated` — assert analysis.stage2_kills is populated from CSV before summary_verdict() is called.

---

## Critical Traps

**Trap 1: The DIAMOND naming collision**
Stage 2 tier "Diamond" (capitalized, from HP sieve) is NOT the same as Stage 3 verdict "DIAMOND"
(all-caps, from DCF). Always use stage2_tier and stage3_verdict as distinct column names.

**Trap 2: Forgetting to populate stage2_kills before calling summary_verdict()**
If you forget to parse the stage2_kills column into analysis.stage2_kills, every name with kills
will appear to have zero kills and earn an undeserved DIAMOND verdict. See reconstruction function above.

**Trap 3: Using stale Stage 2 price for the MOS comparison**
Always fetch a fresh Finviz quote. The Stage 2 price may be hours old.

**Trap 4: stage3_analysis() returning None**
Check for None return before calling summary_verdict(). Produce a QC FAIL row with
qc_fail_reason = "stage3_analysis returned None".

**Trap 5: Offline mode is for contract testing only**
With --offline-input-only, the DCF will QC FAIL on all names because analysis.sec will be None.
Document this clearly in the run log.

---

## Recommended First Run Command

```bash
python -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond
```

Run Diamond only first. Verify the 6 Diamond names produce credible DCF outputs.
Check that SEC data fetched correctly (no all-QC-FAIL run). Then expand tiers.

---

## File Layout After Build

```
stages/stage3/
├── mission.md
├── verdict.md                          <- update after first live run
├── README.md
├── code/
│   ├── README.md                       <- this file
│   └── run_stage3.py                   <- build this
├── output/
│   ├── README.md
│   └── Stage3_Report.csv               <- generated by runner
└── audit_logs/
    ├── README.md
    ├── stage3_build_brief_20260525.md
    ├── stage3_run_<timestamp>.log      <- generated by runner
    └── stage3_run_<timestamp>.jsonl    <- generated by runner
```
