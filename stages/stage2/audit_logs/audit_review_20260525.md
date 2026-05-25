# SignalForge Stage 2 Audit Review

**Date:** 2026-05-25
**Auditor:** Hermes Gatekeeper (pre-production review)
**Scope:** Full read of all docs, mission files, verdict files, run logs, JSONL audit artifacts, and source code across Stage 1 and Stage 2. `stage2_report.py` root wrapper confirmed as clean thin passthrough with no divergent logic.

---

## Overall Verdict

**Stage 1: CLEAR.** The pipeline is mechanically sound, deterministic, and auditable. Data model, field handling, repair logic, and audit logging are all clean. Stage 1 can advance.

**Stage 2: NOT CLEARED FOR PRODUCTION.** Three blocking issues must be resolved before a live run is valid. Additional medium and low items are logged below and should be tracked.

---

## CRITICAL — Blockers (must fix before any live Stage 2 run)

### CRIT-1 — `ChartPatternTest` SMA comparisons are semantically broken in live mode

**File:** `stages/stage2/code/stage2_sieve.py`, lines 158–162

**Problem:** `parse_finviz_quote()` in `screener.py` populates `sma50` and `sma200` from Finviz's `SMA50` / `SMA200` labels. Finviz expresses these as **percent deviation from the moving average** (e.g., `SMA200 = 5.2` means the stock is 5.2% above its 200-day SMA). They are not absolute price values.

`ChartPatternTest` then executes:

```python
if price is not None and q.sma200 and price < q.sma200:
    return result(self.name, BAD, "Broke 200-day moving average")
if price is not None and q.sma50 and price < q.sma50:
    return result(self.name, WEAK, "Broke 50-day moving average but not 200-day")
```

This compares a stock price ($10–$75) against a percent deviation (typically 1–15). The condition is structurally almost always `False`. A $30 stock is never less than the number 4.7. Both SMA checks are effectively dead in live mode. Broken charts pass the Stage 2 chart test without penalty.

**Fix:** Convert the percent-deviation back to an approximate absolute SMA price before comparing:
```python
sma200_price = price / (1 + q.sma200 / 100)
if price < sma200_price: ...
```
Or rename the fields to `sma200_pct_from` and document what they store, then rebuild the check against the correct abstraction.

---

## HIGH — Significant Logic Errors

### HIGH-1 — Stage 2 offline mode is a near-rubber stamp; committed run result is not a valid sieve

**File:** `stages/stage2/audit_logs/stage2_run_20260525T161635Z.log` and `.jsonl`
**Referenced by:** `stages/stage2/README.md` (Latest offline contract run section), `stages/stage2/verdict.md`

**Problem:** The committed offline run shows 71/71 PASS, 0 Watch, 0 Eliminated. This is not a sieve result — it is a structural consequence of what data is absent from `Stage1_PASS.csv`.

In `--offline-input-only` mode the `TickerAnalysis` object has:

| Field | Status in offline CSV | Effect on test |
|---|---|---|
| `news` / headlines | Not present | `IVSpikeDiagnosisTest` → auto-PASS; `NewsSentimentTest` → auto-PASS; `MemeStockTest` → no keyword signal |
| `price_history` | Not fetched | Crash detection and 50%+ rally checks disabled in IV, Meme, and Chart tests |
| `sma50` / `sma200` / `week_52_high` / `week_52_low` | Not in CSV | `ChartPatternTest` → auto-PASS (falls through to last return) |
| `inst_own` | Not in CSV | `InstitutionalOwnershipTest` → SKIP on every row (confirmed in output CSV) |
| `target_price` / `price` | Present via `one_yr_target` / `price_proxy` | `AnalystConsensusTest` → works |
| Liquidity fields | Present | `LiquidityTest` → works |

**Result:** Only 2 of 7 tests produce meaningful verdicts in offline mode. The other 5 are auto-PASS or auto-SKIP. The 71/71 PASS outcome is mathematically guaranteed by the input, not earned by the sieve.

The README and verdict.md must not present this run as evidence Stage 2 is functionally complete. It should be labeled explicitly:

> This run validates the output column contract and runner mechanics only. It is not a representation of live sieve results. In live mode, all seven tests evaluate independently against fetched data.

### HIGH-2 — `InstitutionalOwnershipTest` insider sell check is unreachable for borderline-ownership stocks

**File:** `stages/stage2/code/stage2_sieve.py`, lines 221–234

**Problem:**

```python
if q.inst_own < 30:
    return result(self.name, BAD, ...)
if q.inst_own <= 50:
    return result(self.name, WEAK, ...)
if q.insider_trans is not None and q.insider_trans <= -20:
    return result(self.name, BAD, ...)   # only reachable if inst_own > 50
```

A stock with 40% institutional ownership and active insider dumping (`insider_trans = -50%`) returns WEAK and never reaches the insider sell check. The BAD insider sell signal is only evaluated when institutional ownership is already strong (> 50%). This misses the most dangerous combination: weak institutional backing plus active insider selling.

**Fix:** Elevate the `insider_trans` check to run independently of the ownership tier, or check it before returning WEAK:

```python
if q.inst_own < 30:
    return result(self.name, BAD, ...)
if q.insider_trans is not None and q.insider_trans <= -20:
    return result(self.name, BAD, ...)
if q.inst_own <= 50:
    return result(self.name, WEAK, ...)
```

### HIGH-3 — Dead code `_stage2_add_test` in `screener.py` carries wrong HP semantics

**File:** `screener.py`, lines 612–629

**Problem:** The function `_stage2_add_test()` is never called (Stage 2 now runs exclusively through `Stage2Sieve`). However, its body assigns:

```python
"hp_loss": 1 if status == "KILL" else 0,
```

This uses the pre-HP vocabulary ("KILL") and assigns a flat 1 regardless of signal severity. The live sieve contract is `{PASS:0, WEAK:1, BAD:2, SKIP:0}`. If this dead function is accidentally wired up, it silently halves all BAD penalties and collapses the tier distinction. It should be deleted, not left dormant.

### HIGH-4 — `_value_missing` in Step 3 treats `iv_rank = 0` as missing, triggering spurious retries

**File:** `stages/stage1/code/step3_barchart_enrichment.py`, lines 91–101

**Problem:**

```python
try:
    return float(match.group(0)) <= 0
except ValueError:
    return True
```

`barchart_iv_rank = 0` is a legitimate reading (IV sitting at its 52-week floor). This code classifies it as a missing field and schedules the row for a repair round retry. For stocks genuinely at their IV low, every pipeline run produces noisy retries and the unresolved log reports them as unfetchable.

The intent appears to be "field is absent or non-numeric." The `<= 0` check overshoots that intent.

**Fix:** Remove the numeric value check entirely. Treat any parseable number as present:

```python
return match is None  # field is missing if no number found
```

---

## MEDIUM — Documentation and Consistency Issues

### MED-1 — `docs/project-layout.md` maps Stage 1 to `screener.py` — stale and misleading

**File:** `docs/project-layout.md`

The document states:
> Stage 1: `screener.py`, `market_cap_census.py`, `nasdaq_market_cap_census.py`

Canonical Stage 1 now lives in `stages/stage1/code/step1–4*.py`. `screener.py` is the live single-ticker path. The project layout doc needs to be updated to reflect the current architecture before any new contributor reads it.

### MED-2 — Step numbering conflict across README files and code filenames

The "complete Stage 1 output" step is called:
- "Step 4" in the root `README.md`
- "Step 5" in `stages/stage1/README.md` and `stages/stage1/verdict.md`
- Named `step4_complete_stage1_output.py` in the code
- Emits audit event `stage1_step5_complete_output_complete` in the JSONL

Three different numbering schemes for the same step. The run commands in the stage1 README invoke `step4_complete_stage1_output` under a "Step 5" heading, which will silently confuse contributors and produce wrong cross-references. Pick one canonical numbering and make it consistent everywhere.

### MED-3 — Stage 2 verdict.md presents offline run as stage completion without qualification

**File:** `stages/stage2/verdict.md`

The verdict states Stage 2 is complete and references the offline run counts as confirmation. Per HIGH-1 above, those counts are not evidence the sieve works. The verdict file needs a qualification paragraph clarifying that live-data tests (news, price history, SMA, institutional ownership) have not been validated against live fetches yet and remain to be verified on the first live run.

---

## LOW — Minor Fragility Items (track, do not block)

### LOW-1 — `parse_finviz_quote` sets `volume` to Rel Volume if "Volume" key is absent

**File:** `screener.py`, lines 197–219

If Finviz drops the "Volume" label (layout change), `quote.volume` silently becomes a relative ratio (e.g., 1.2). Every stock then fails the 1M-share Stage 1 volume filter silently — no error, just a universal Stage 1 failure. The code comment acknowledges the overwrite intention. A defensive None fallback and explicit log on the code path would eliminate the silent failure mode.

### LOW-2 — `stage2_score` conflates "tested and good" with "untestable"

`SKIP` produces `score = 0.0`, identical to a failed test. In offline mode all 71 names are penalized on their `stage2_score` for the institutional ownership SKIP. The score as-is cannot distinguish between a stock that earned its rating and one where data was simply unavailable. This should be documented or a separate `tested_count` field added if score is used for Stage 3 prioritization.

### LOW-3 — `stage2_report.py` root wrapper confirmed clean

`stage2_report.py` is a pure thin passthrough: imports `main` and `run` from `stages.stage2.code.run_stage2` and raises `SystemExit(main())`. No divergent logic. No issues.

---

## Confirmed Clean Items

- Stage 1 Steps 1–5: deterministic, auditable, bounded repair logic, correct PASS/FAIL classification, proper Stage 2 handoff. Verified against run logs.
- `run_stage2.py` orchestration: threading, index-order output, audit JSONL, human progress log, error isolation via `_failed_analysis`. All correct.
- `stage2_sieve.py` HP framework structure: PASS/WEAK/BAD/SKIP damage map, tier boundaries, 10-HP starting value, Stage 1 pass state preservation — all match the spec in `verdict.md`.
- `LiquidityTest` and `AnalystConsensusTest`: thresholds and logic are correct for the live path.
- `step4_options_liquidity_enrichment.py`: cache-first strategy, Finviz fallback, missing-field tracking, and audit event are all correct.
- `stage2_report.py` legacy wrapper: confirmed thin passthrough.

---

## Required Actions Before Stage 2 Production Clearance

| Priority | Item | File |
|---|---|---|
| CRIT-1 | Fix SMA comparison — convert pct-deviation to absolute price | `stage2_sieve.py` |
| HIGH-1 | Add offline-mode qualification to README and verdict.md | `stages/stage2/README.md`, `verdict.md` |
| HIGH-2 | Fix insider sell check ordering in `InstitutionalOwnershipTest` | `stage2_sieve.py` |
| HIGH-3 | Delete dead `_stage2_add_test` function | `screener.py` |
| HIGH-4 | Remove `<= 0` from `_value_missing` check | `step3_barchart_enrichment.py` |
| MED-1 | Update `docs/project-layout.md` to reflect current architecture | `docs/project-layout.md` |
| MED-2 | Resolve step numbering conflict (Step 4 vs Step 5) | `README.md`, `stages/stage1/README.md` |
| MED-3 | Add live-data qualification note to Stage 2 verdict | `stages/stage2/verdict.md` |
