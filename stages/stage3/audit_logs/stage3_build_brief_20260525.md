# Auditor Notes — Stage 3 Build Brief

**Date:** 2026-05-25
**Auditor:** Hermes Gatekeeper
**For:** Hermes (Stage 3 implementation)

---

## Status

Stage 2 is production-cleared. The live validation run completed clean: 71/71 symbols processed,
0 errors, Diamond=6 / Strong=15 / Standard=27 / Watch=17 / Eliminated=6. All five audit blockers
confirmed working in live data.

Stage 3 has never been run as a batch pipeline. The DCF engine exists in `screener.py` and is
correct. What does not exist is the batch runner. That is your build target.

---

## What You Are Building

`stages/stage3/code/run_stage3.py` — a batch pipeline runner that:

1. Reads `Stage2_Report.csv`
2. Filters to eligible tiers (non-Eliminated) in cascade order
3. Fetches live price (Finviz) and SEC companyfacts per symbol
4. Calls `stage3_analysis()` from `screener.py`
5. Writes `Stage3_Report.csv`
6. Emits JSONL audit events and a human-readable run log

Full technical specification is in `stages/stage3/code/README.md`. Read it completely before
writing anything.

---

## The Three Things Most Likely to Go Wrong

### 1. Forgetting to populate `stage2_kills` before calling `summary_verdict()`

`summary_verdict()` checks `len(analysis.stage2_kills)`. If you reconstruct the `TickerAnalysis`
from the CSV row and forget to parse the `stage2_kills` column into `analysis.stage2_kills`, every
name will appear to have zero kills. Names that earned 1–2 kills in Stage 2 will be upgraded from
`ENTRY` to `DIAMOND`. That is a silent correctness failure — no crash, no error, wrong answer.

The fix is in the reconstruction function. Parse the `stage2_kills` column (pipe-delimited) into
`analysis.stage2_kills` before calling anything that touches `summary_verdict()`.

### 2. Using stale Stage 2 price for the MOS comparison

The DCF `mos_threshold` is compared against `q.price`. If you set `q.price` from the Stage 2 CSV
instead of fetching it fresh from Finviz, you are comparing today's MOS threshold against a price
that may be hours old. For a volatile name, this can flip a `NO ENTRY` to `ENTRY` or vice versa.

Always fetch a fresh Finviz quote per symbol. It is one HTTP call. Do not skip it.

### 3. Misreading `stage3_analysis()` returning `None`

If `analysis.sec` is `None` or `analysis.quote.price` is `None`, `stage3_analysis()` returns a
`qc_fail()` dict — it does NOT return `None` in most paths. But it returns `None` only if the APLD
custom model path is tried and falls through (symbol is not APLD). For all non-APLD symbols, the
function returns a dict. Check the return value for `verdict == "QC FAIL"` rather than checking
for `None`. Both cases should produce a `QC FAIL` row in your output.

---

## Cascade Logic — Understand the Intent

The cascade exists to save bandwidth. If 6 Diamond names yield 5+ DIAMOND/ENTRY verdicts,
there is no reason to fetch SEC data and Finviz quotes for the remaining 59 names.

The cascade threshold (`--min-verdicts`) defaults to 5. This is a starting point, not a law.
If you run Diamond only and get 3 DIAMOND + 2 ENTRY = 5 actionable names, cascade stops.
If you get 1 DIAMOND + 1 ENTRY = 2, cascade continues to Strong.

**Log the cascade decision clearly.** The audit log should state:
- How many symbols were processed in each tier
- What the actionable count was after each tier
- Whether cascade stopped early and why, or ran to completion

---

## SEC Data Expectations

The SEC companyfacts API (`https://data.sec.gov/api/xbrl/companyfacts/{cik}.json`) is:
- Free, no API key required
- Rate limit: informal, ~10 requests/second is safe, 2 workers is fine
- Coverage: most exchange-listed equities have entries; small-caps and recent IPOs may not
- Staleness: data updates after SEC filings, typically quarterly

For the 6 Diamond names (MARA, CLSK, PCT, QUBT, USAR, UUUU):
- All are public companies with SEC filings
- All are Category B (pre-profitable or marginal cash flow) — expect 50% MOS thresholds
- MARA and CLSK are Bitcoin miners — high revenue volatility, expect wide scenario ranges
- QUBT and PCT are early-stage names — revenue may be near zero; DCF may QC FAIL

If QUBT or PCT come back as `QC FAIL` on `zero or missing revenue`, that is expected, not a bug.
Document it in the audit log and move to the next name.

---

## Naming Collision — Do Not Get Confused

Stage 2 uses tier labels: `Diamond / Strong / Standard / Watch / Eliminated`
Stage 3 uses verdict labels: `DIAMOND / ENTRY / NO ENTRY / QC FAIL`

These share the word "Diamond" and mean different things:
- **Stage 2 Diamond** = survived HP sieve with 9–10 HP remaining
- **Stage 3 DIAMOND** = DCF says price is at or below MOS threshold AND zero Stage 2 kills

A Stage 2 Diamond name can produce a Stage 3 `NO ENTRY` if the stock is currently overvalued
relative to its DCF fair value. This is correct behavior. Do not treat it as a bug.

In all output columns, CSV headers, and log messages: always use `stage2_tier` and `stage3_verdict`
as distinct field names. Never use the bare word "diamond" in a context where it could refer
to either tier system.

---

## What Stage 3 Explicitly Does NOT Build

Do not add any of the following to Stage 3:

- **Strike selection or DTE analysis** — these require current IV surface data and belong downstream
- **Premium yield calculation** — requires live options chain, not available here
- **Earnings date clearance** — requires earnings calendar integration, not present in current data pipeline
- **Portfolio or position awareness** — Stage 3 has no access to current holdings
- **AI trade confirmation** — that layer requires position context and comes after Stage 3

If you find yourself computing any of the above, stop. You are building Stage 4, not Stage 3.
Stage 3 answers one question: *Is this stock worth owning at today's price?* DCF answers that.
Everything else is out of scope until the downstream trade layer is designed.

---

## Acceptance Criteria

A Stage 3 run is valid when:

1. All eligible symbols in the processed tiers have a row in the output CSV (no silent drops)
2. Zero unhandled exceptions — every error produces a `QC FAIL` row with a reason string
3. `stage2_kills` is correctly propagated — cross-check: any name with kills in Stage 2 output
   should not be showing `DIAMOND` verdict in Stage 3 output unless kills were re-evaluated
4. Audit JSONL contains `stage3_run_start`, one `stage3_symbol_result` per processed symbol, and `stage3_run_complete`
5. The `DIAMOND` + `ENTRY` count is non-zero for a live run against real SEC data
   (if all names return `QC FAIL` or `NO ENTRY`, something is wrong with SEC fetches)
6. Cascade logic log matches actual behavior — if log says "cascade stopped after Diamond tier",
   the output CSV should contain only Diamond-tier rows

Run the Diamond tier in isolation first. Verify outputs are credible before expanding to other tiers.

---

## Regression Test Requirements

At minimum, write tests for:

- Cascade stops early when threshold met
- Cascade continues when threshold not met
- Exception in one symbol does not abort the run
- Output CSV sorted correctly by tier then score
- `stage2_kills` correctly propagated from CSV into `summary_verdict()` logic

These are not optional. The Stage 2 audit was blocked on correctness failures that would have
been caught by tests. Stage 3 ships with tests or it does not ship.

---

## Final Note

The DCF engine is the right tool for this job. The MOS threshold is conservative by design —
50% of weighted fair value for Category B names. You will likely see most of the 65 names
return `NO ENTRY` because they are high-IV speculative names trading at or above fair value.
That is the expected result. Stage 3 is a filter, not a rubber stamp.

If the Diamond tier yields 2–3 actionable names from 6 symbols, that is a healthy and realistic
outcome. Do not tune parameters to produce more `DIAMOND` or `ENTRY` verdicts. The thresholds
in `stage3_analysis()` are deliberate. Work with them.
