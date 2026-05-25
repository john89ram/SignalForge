# Stage 3 — Build Specification for run_stage3.py

**Author:** Hermes Gatekeeper (Auditor)
**Date:** 2026-05-25
**Revision:** 3 — constructor fix + defensive kill parsing + eligibility guard (Hermes review)
**Status:** Ready to build — all dependencies confirmed present in codebase

---

## Overview

Stage 3 needs a canonical batch runner: `stages/stage3/code/run_stage3.py`.
This mirrors the architecture of `stages/stage2/code/run_stage2.py` — read a CSV, process
symbols concurrently, write an output CSV, emit JSONL audit events.

The DCF engine already exists. Do not rewrite it. Your job is to build the pipeline
wrapper around it.

---

## BEFORE YOU RUN: git pull required

The local filesystem may have the offline Stage2_Report.csv (Diamond=21/Strong=38/Standard=12).
The correct live input (Diamond=6/Strong=15/Standard=27/Watch=17/Eliminated=6) is in git.
Always run `git pull` before executing Stage 3 or you will be running against offline data.

---

## What Already Exists — Do Not Rewrite

All of the following are production-ready in `screener.py`. Import them directly.

```python
from screener import (
    TickerAnalysis,
    QuoteSnapshot,
    BarchartSnapshot,
    OptionsSnapshot,
    SECFacts,
    load_sec_companyfacts,
    parse_finviz_quote,
    stage3_analysis,
    summary_verdict,
    HTTP,
)
```

- `stage3_analysis(analysis: TickerAnalysis) -> Optional[Dict[str, Any]]`
  The complete DCF engine. Handles Category A/B classification, 5-year FCF projection,
  scenario weighting, share QC, and the APLD bespoke model. Returns a dict or None.

- `summary_verdict(a: TickerAnalysis) -> str`
  Maps a TickerAnalysis to exactly one of: DIAMOND, ENTRY, NO ENTRY, QC FAIL.
  Uses `len(analysis.stage2_kills)` — this MUST be populated before calling it.

- `load_sec_companyfacts(http: HTTP, symbol: str) -> Optional[SECFacts]`
  Fetches from https://data.sec.gov/api/xbrl/companyfacts/{cik}.json
  Free API. No authentication. 2 workers is appropriate.

- `parse_finviz_quote(html: str, symbol: str) -> QuoteSnapshot`
  Used to get a live price snapshot for the MOS comparison.

---

## Input Contract — Actual Stage 2 Column Names

**File:** `stages/stage2/output/Stage2_Report.csv`

The build brief (Revision 1) used proposed names that differ from the actual live output.
Use the actual column names below. Apply aliases so the runner works with both current
and any future renamed columns.

| Actual Stage 2 column | Brief name (alias) | Used for |
|---|---|---|
| `symbol` | — | Ticker lookup |
| `hp_tier` | `stage2_tier` | Tier-cascade filtering |
| `stage2_score` | — | Output sort order within tier |
| `stage2_hp_left` | — | Pass-through to output |
| `stage2_verdict` | — | Pass-through (PASS / ELIMINATED) |
| `stage2_bad_text` | `stage2_kills` | Pipe-delimited BAD verdict details |
| `stage2_bad_count` | — | Integer count of BAD verdicts |
| `stage2_weak_text` | `stage2_flags` | Pipe-delimited WEAK verdict details |
| `price_proxy` | — | Reference price (NOT used for MOS — fetch fresh) |
| `eligible_for_stage3` | — | Pre-filter guard |

**Columns absent from Stage 2 output** (leave blank in Stage 3 output, do not crash):
- `iv_rank` — not present; use `row.get("iv_rank", "")`
- `implied_vol` — not present; use `row.get("implied_vol", "")`

**Tier values in live output:** Diamond, Strong, Standard, Watch, Eliminated

Eliminated symbols must be skipped. Do not fetch or process them.

---

## Alias Helper

Apply aliases at the CSV parsing boundary so the runner is resilient to future renames:

```python
def _get_tier(row: dict) -> str:
    """Resolve tier from actual or aliased column name."""
    return row.get("stage2_tier") or row.get("hp_tier", "")

def _get_kills_text(row: dict) -> str:
    """Resolve BAD verdict text from actual or aliased column name."""
    return row.get("stage2_kills") or row.get("stage2_bad_text", "")

def _get_flags_text(row: dict) -> str:
    """Resolve WEAK verdict text from actual or aliased column name."""
    return row.get("stage2_flags") or row.get("stage2_weak_text", "")

def _is_stage3_eligible(row: dict) -> bool:
    """Return True if this Stage 2 row should be processed by Stage 3."""
    tier = _get_tier(row)
    eligible_text = str(row.get("eligible_for_stage3", "TRUE")).strip().upper()
    eligible = eligible_text not in {"FALSE", "0", "NO", "N"}
    return tier != "Eliminated" and eligible
```

---

## Reconstructing TickerAnalysis from CSV

`stage3_analysis()` requires a `TickerAnalysis` object. Reconstruct it from the Stage 2
CSV row + fresh fetches.

```python
def _analysis_from_stage2_row(row: dict, http: HTTP) -> TickerAnalysis:
    symbol = row["symbol"].strip().upper()

    # Fresh price fetch — Stage 2 price_proxy may be hours old; MOS comparison needs today's price
    finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
    q = parse_finviz_quote(finviz_html, symbol)

    analysis = TickerAnalysis(
        symbol=symbol,
        quote=q,
        barchart=BarchartSnapshot(),
        options=OptionsSnapshot(),
    )
    analysis.stage1_pass = True  # Only eligible names reach Stage 3

    # CRITICAL: populate stage2_kills from pipe-delimited bad text BEFORE calling summary_verdict()
    # Use stage2_bad_count as the authoritative count; parse text for detail if present.
    bad_text = _get_kills_text(row)
    parsed_kills = [k.strip() for k in bad_text.split("|") if k.strip()] if bad_text else []
    raw_bad_count = row.get("stage2_bad_count")
    bad_count = int(raw_bad_count) if raw_bad_count not in (None, "") else None
    if bad_count is None:
        analysis.stage2_kills = parsed_kills
    elif parsed_kills and len(parsed_kills) == bad_count:
        analysis.stage2_kills = parsed_kills
    elif bad_count > 0:
        analysis.stage2_kills = parsed_kills if len(parsed_kills) >= bad_count else ["kill"] * bad_count
    else:
        analysis.stage2_kills = []

    flags_text = _get_flags_text(row)
    analysis.stage2_flags = [f.strip() for f in flags_text.split("|") if f.strip()] if flags_text else []

    analysis.stage2_tier = _get_tier(row)
    analysis.stage2_score = float(row.get("stage2_score", 0.0) or 0.0)
    analysis.stage2_hp_left = int(row.get("stage2_hp_left", 0) or 0)
    analysis.eligible_for_stage3 = True  # Guaranteed by tier filter above

    # SEC fetch — primary data source for DCF
    analysis.sec = load_sec_companyfacts(http, symbol)

    return analysis
```

---

## Cascade Logic

Tier-ordered cascade to avoid burning API calls on all 65 eligible names when the top
tier alone yields enough actionable results.

**CLI argument:** `--min-verdicts N` (default: 5)
Minimum count of DIAMOND + ENTRY verdicts before cascade stops.

**Behavior:**
1. Process all Diamond-tier symbols
2. Count DIAMOND + ENTRY verdicts
3. If count >= --min-verdicts, stop. Log the decision.
4. Otherwise process Strong. Re-evaluate count.
5. Continue through Standard, then Watch.
6. Log which tiers were consumed and why cascade continued or stopped.

`--min-verdicts 0` disables the cascade and processes all eligible requested tiers.
Default should be 5 for production. Use 0 for full validation runs.

**Tier filter argument:** `--tiers Diamond,Strong,Standard,Watch` (default: all four)
Allows running a single tier in isolation for debugging.

---

## Concurrency

Use `concurrent.futures.ThreadPoolExecutor` with `--workers` (default: 2, max recommended: 3).
SEC API is tolerant; Finviz is not. Do not exceed 3 workers.

Error isolation: wrap each symbol in try/except. On exception, emit QC FAIL.
Never let one symbol crash the run.

```python
def _failed_analysis(symbol: str, stage2_row: dict, reason: str) -> dict:
    """Return a QC FAIL row when an exception occurs."""
    return {
        "symbol": symbol,
        "stage2_tier": _get_tier(stage2_row),
        "stage2_score": stage2_row.get("stage2_score", ""),
        "stage2_hp_left": stage2_row.get("stage2_hp_left", ""),
        "stage3_verdict": "QC FAIL",
        "stage3_category": "",
        "weighted_fair_value": "",
        "mos_threshold": "",
        "current_price": "",
        "undervaluation_pct": "",
        "bear_value": "",
        "realistic_value": "",
        "bull_value": "",
        "qc_fail_reason": reason,
        "share_count_source": "",
        "share_qc_detail": "",
        "watch_signal": "",
        "kill_signal": "",
        "stage2_kills": _get_kills_text(stage2_row),
        "stage2_flags": _get_flags_text(stage2_row),
        "sector": stage2_row.get("sector", ""),
        "iv_rank": "",
        "implied_vol": "",
    }
```

---

## Output Contract — Stage3_Report.csv

Write to `stages/stage3/output/Stage3_Report.csv`.

| Column | Source | Notes |
|---|---|---|
| `symbol` | Stage 2 CSV | |
| `stage2_tier` | `hp_tier` from CSV | Diamond/Strong/Standard/Watch |
| `stage2_score` | Stage 2 CSV | 0.0–7.0 |
| `stage2_hp_left` | Stage 2 CSV | 0–10 |
| `stage3_verdict` | `summary_verdict()` | DIAMOND/ENTRY/NO ENTRY/QC FAIL |
| `stage3_category` | `s3["category"]` | A or B |
| `weighted_fair_value` | `s3["weighted_fair_value"]` | float or blank |
| `mos_threshold` | `s3["mos_threshold"]` | float or blank |
| `current_price` | `s3["current_price"]` | float (from fresh Finviz fetch) |
| `undervaluation_pct` | `s3["undervaluation_pct"]` | positive = undervalued |
| `bear_value` | `s3["bear"]` | per-share bear scenario |
| `realistic_value` | `s3["realistic"]` | per-share realistic scenario |
| `bull_value` | `s3["bull"]` | per-share bull scenario |
| `qc_fail_reason` | `s3["qc_fail_reason"]` | blank unless QC FAIL |
| `share_count_source` | `s3["share_count_source"]` | "sec" or "market_cap_implied" |
| `share_qc_detail` | `s3["share_qc_detail"]` | blank unless QC mismatch |
| `watch_signal` | `s3["watch_signal"]` | text or blank |
| `kill_signal` | `s3.get("kill_signal")` | text or blank (APLD only) |
| `stage2_kills` | `stage2_bad_text` from CSV | pass-through |
| `stage2_flags` | `stage2_weak_text` from CSV | pass-through |
| `sector` | Stage 2 CSV | pass-through |
| `iv_rank` | blank | not in Stage 2 output |
| `implied_vol` | blank | not in Stage 2 output |

**Sort order:** Tier order, then `stage2_score` descending, then `symbol` alphabetically.

```python
TIER_ORDER = {"Diamond": 0, "Strong": 1, "Standard": 2, "Watch": 3, "Eliminated": 4, "": 5}
```

---

## Audit Logging

Emit four JSONL event types to `stages/stage3/audit_logs/stage3_run_<timestamp>.jsonl`:

**stage3_run_start:**
```json
{
  "event": "stage3_run_start",
  "timestamp": "2026-05-25T18:00:00Z",
  "input_csv": "stages/stage2/output/Stage2_Report.csv",
  "total_eligible": 65,
  "tiers_requested": ["Diamond", "Strong", "Standard", "Watch"],
  "min_verdicts": 5,
  "workers": 2,
  "input_tier_counts": {"Diamond": 6, "Strong": 15, "Standard": 27, "Watch": 17, "Eliminated": 6}
}
```

**stage3_symbol_result** (one per processed symbol):
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

**stage3_cascade_decision** (emit after each tier completes):
```json
{
  "event": "stage3_cascade_decision",
  "tier_completed": "Diamond",
  "symbols_in_tier": 6,
  "cumulative_symbols": 6,
  "cumulative_actionable": 3,
  "min_verdicts_threshold": 5,
  "decision": "continue",
  "reason": "actionable count 3 below threshold 5"
}
```

**stage3_run_complete:**
```json
{
  "event": "stage3_run_complete",
  "timestamp": "2026-05-25T18:05:00Z",
  "tiers_consumed": ["Diamond", "Strong"],
  "cascade_stopped_early": true,
  "symbols_processed": 21,
  "verdicts": {"DIAMOND": 2, "ENTRY": 5, "NO ENTRY": 12, "QC FAIL": 2},
  "actionable_count": 7,
  "runtime_seconds": 148.2,
  "output_csv": "stages/stage3/output/Stage3_Report.csv"
}
```

---

## CLI Interface

```bash
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
| `--min-verdicts` | 5 | Cascade stops when DIAMOND+ENTRY >= this; 0 = process all |
| `--tiers` | all four | Comma-separated ordered list |
| `--offline-input-only` | False | Skip live fetches. Contract testing only — DCF will QC FAIL. |

---

## Regression Tests

Write tests in `tests/test_stage3_runner.py`. All ten are required:

**Original five (from build brief):**
1. `test_tier_cascade_stops_early` — mock enough Diamond DIAMOND+ENTRY to meet threshold; assert Strong never processed.
2. `test_tier_cascade_continues` — mock too few Diamond actionable verdicts; assert Strong is processed.
3. `test_failed_analysis_isolation` — mock one symbol raising an exception; assert QC FAIL row present and others processed.
4. `test_output_sort_order` — mixed tier input; assert Diamond first, then stage2_score descending, then symbol.
5. `test_stage2_kills_propagated` — assert stage2_kills populated from stage2_bad_text before summary_verdict() is called.

**Added from Hermes handoff review:**
6. `test_current_stage2_column_aliases_are_supported` — input row with `hp_tier`, `stage2_bad_text`, `stage2_weak_text`; assert runner reads them correctly. This directly guards the schema mismatch.
7. `test_min_verdicts_zero_processes_all_requested_tiers` — assert cascade disabled when --min-verdicts 0.
8. `test_stage3_analysis_none_becomes_qc_fail_row` — mock `stage3_analysis()` returning None; assert QC FAIL output with clear reason.
9. `test_eliminated_stage2_rows_are_skipped` — input with an Eliminated row; assert it is never fetched or processed.
10. `test_audit_jsonl_contains_all_event_types` — assert start, symbol_result (one per symbol), cascade_decision, and complete events all present.

---

## Critical Traps

**Trap 1: stage2_kills silent empty**
If you read `stage2_kills` from the CSV and that column doesn't exist (current output uses `stage2_bad_text`),
every name reconstructs with zero kills. Names with 1–2 BAD verdicts earn undeserved DIAMOND verdicts.
Use the alias helpers above. Test 6 guards this.

**Trap 2: Stale price**
Always fetch fresh Finviz quote. `price_proxy` in the Stage 2 CSV may be hours old.
A volatile name can swing enough intraday to flip the MOS verdict.

**Trap 3: stage3_analysis() None vs QC FAIL dict**
Most failure paths return a dict with `verdict == "QC FAIL"`. The function returns actual None
only in edge cases. Handle both: check for None, then check for `verdict == "QC FAIL"`.

**Trap 4: DIAMOND naming collision**
Stage 2 tier "Diamond" != Stage 3 verdict "DIAMOND". Use `stage2_tier` and `stage3_verdict`
as distinct field names everywhere — CSV headers, log lines, JSONL events.

**Trap 5: git pull before running**
The local Stage2_Report.csv may be from the offline run (Diamond=21). The live run CSV
(Diamond=6/Strong=15/Standard=27/Watch=17/Eliminated=6) is in git at b923820.
Always pull before running Stage 3.

---

## Recommended First Run Command

```bash
git pull
python -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond
```

Run Diamond only first (6 symbols). Verify SEC fetches, DCF outputs, and cascade logging
are all credible before expanding tiers.

---

## File Layout After Build

```
stages/stage3/
├── mission.md
├── verdict.md                          <- update after first live run
├── README.md
├── code/
│   ├── README.md                       <- this file (Revision 2)
│   └── run_stage3.py                   <- build this
├── output/
│   ├── README.md
│   └── Stage3_Report.csv               <- generated by runner
└── audit_logs/
    ├── README.md
    ├── stage3_build_brief_20260525.md
    ├── stage3_handoff_review_20260525T193038Z.md
    ├── stage3_run_<timestamp>.log      <- generated by runner
    └── stage3_run_<timestamp>.jsonl    <- generated by runner
```
