# Auditor Clearance — screener.py Remediation + Post-Fix Cascade Run

**Date:** 2026-05-25  
**Auditor:** Hermes Gatekeeper  
**Scope:** screener.py BUG-1 (revenue tag fallback) + BUG-2 (directional share sanity) + post-fix Diamond+Strong cascade  
**Commit reviewed:** 213108f  
**Test count:** 64 passed, 3 subtests passed  

---

## Decision

**CLEARED.** Both fixes are correctly implemented, tested, and live-validated. The Diamond+Strong cascade run is mechanically clean. Cascade must continue to Standard tier — 0 actionable names found in Diamond+Strong combined.

---

## BUG-1 — Revenue Tag Fallback

**Status: GREEN**

`load_sec_companyfacts()` now iterates a priority-ordered tuple of four revenue tags:

1. `RevenueFromContractWithCustomerExcludingAssessedTax`
2. `RevenueFromContractWithCustomerIncludingAssessedTax`
3. `Revenues`
4. `SalesRevenueNet`

For each tag that returns rows, annual rows are preferred (`fp == "FY"` or `form in {10-K, 20-F, 40-F}`). If annual rows exist, extraction stops at that tag. If no annual rows are found from any tag, the first non-empty tag's rows are used as a quarterly fallback. Implementation is correct and handles the annual preference watch item proactively.

**Verified:** 4 test cases in `tests/test_screener.py` covering tag fallbacks and annual preference. All pass.

---

## BUG-2 — Directional Share Sanity Check

**Status: GREEN**

Both check locations (~line 730 APLD path, ~line 906 generic path) now use:

```python
upside_delta = (implied_mktcap - q.market_cap) / q.market_cap
if upside_delta > 0.20:
    return qc_fail("share denominator sanity failed: ...")
```

Only fires when DCF-implied market cap is materially above the quoted market cap (+20% threshold). Low DCF values (overvalued names) correctly produce NO ENTRY rather than a false QC FAIL.

**Verified:** 2 test cases in `tests/test_screener.py` — low-implied passes, high-implied still fails. Both pass.

---

## Post-Fix Run Audit

### Mechanics

- JSONL event count: 25 (1 run_start + 21 symbol_results + 2 cascade_decisions + 1 run_complete). Correct.
- All 21 eligible symbols in Diamond+Strong have a row in the output CSV. No silent drops.
- Zero unhandled exceptions. All errors produce QC FAIL rows with reason strings.
- CSV sort order: Diamond tier first, then Strong; within each tier by `stage2_score` descending, then symbol alpha as tiebreaker. Verified against output.
- `stage2_kills` propagation confirmed: no Diamond-tier name with kills incorrectly earned a DIAMOND verdict.

### Diamond Tier (6 symbols)

All 6: NO ENTRY, Category B. This is a valid sieve result, not a runner failure. These are high-IV speculative names (Bitcoin miners, quantum computing, uranium) trading at 7–96x their DCF weighted fair values. The MOS gate is doing exactly what it is supposed to do.

| Symbol | WFV | MOS | Price | Overvaluation |
|--------|-----|-----|-------|---------------|
| MARA | $1.28 | $0.64 | $13.81 | 10.8x |
| CLSK | $1.00 | $0.50 | $15.97 | 32.0x |
| PCT | $0.48 | $0.24 | $11.32 | 47.4x |
| QUBT | $1.14 | $0.57 | $12.31 | 21.6x |
| USAR | $8.02 | $4.01 | $25.30 | 6.3x |
| UUUU | $1.51 (A) | $1.21 | $18.04 | 14.9x |

### Strong Tier Cascade (15 symbols)

Processed because Diamond actionable count = 0, below threshold of 5.

Results: 10 NO ENTRY, 5 QC FAIL. Actionable count remains 0.

QC FAIL breakdown:

| Symbol | Reason | Assessment |
|--------|--------|------------|
| PATH | share denominator: implied $7.29B vs known $5.69B (+28.1%) | VALID — directional guard correctly firing. Market cap implies ~2B more shares outstanding than SEC records. |
| RUN | share denominator: implied $14.72B vs known $3.49B (+321.6%) | VALID — large discrepancy likely from undiluted share count in SEC filing vs market reality. |
| BTDR | SEC data unavailable | VALID — Bitdeer is a Cayman Islands company; EDGAR coverage is limited. |
| SOC | zero or missing revenue | SEE WATCH-2 below. |
| UEC | zero or missing revenue | SEE WATCH-2 below. |

---

## Watch Items (Non-Blocking)

### WATCH-1: Negative MOS values — GLXY and RIOT

GLXY (Strong, score 6.0): `weighted_fair_value = -$68.22`, `mos_threshold = -$34.11`. Bear scenario projects -$377.77/share, realistic -$25.00/share, bull +$849.60/share. The extreme negative bear/realistic scenarios pull the weighted mean below zero.

RIOT (Strong, score 5.5): `weighted_fair_value = -$0.24`, `mos_threshold = -$0.119`. Near-zero intrinsic value — bear -$3.66, realistic +$0.24, bull +$9.91.

**This is not a bug.** The comparison `current_price <= mos_threshold` correctly returns NO ENTRY for both (28.65 > -34.11 and 24.49 > -0.12). The math is working as specified. However:

- The `mos_threshold` column in the output CSV containing a negative float is semantically confusing to any downstream consumer of this data.
- Future audit or reporting tools that attempt to interpret MOS as "a floor price to target" will produce nonsense for these names.

**Recommendation for downstream:** When `weighted_fair_value < 0`, suppress numeric MOS from output and substitute a sentinel label like `"neg_intrinsic"` or blank the field. The verdict is already NO ENTRY. The number adds noise without actionable meaning. Not required for this run but flag for Stage 3 v2.

### WATCH-2: SOC and UEC — revenue tag gap for non-standard filers

SOC (Sievert Laryngoscope? — Energy sector) and UEC (Uranium Energy Corp) both return `zero or missing revenue` despite `share_count_source = sec`, meaning their CIK was found and companyfacts retrieved but no revenue row matched any of the four current tags.

UEC is a uranium miner. Mining companies may report under `MiningRevenues`, `RevenueFromMineralSales`, or other sector-specific GAAP tags not in the current fallback list. SOC (Energy sector) may be similar.

**Current behavior:** QC FAIL with clear reason string. This is correct — we do not invent revenue. The QC fail accurately describes the gap.

**Recommendation:** Add `MiningRevenues` and `RevenueFromMineralSales` to the fallback tag list in a future screener.py update. This will not change the verdict for names with genuinely zero revenue but will recover legitimate filers who use non-standard tags. Log as LOW-3.

### WATCH-3: FSLY — closest name to ENTRY across Diamond+Strong

FSLY (Strong, Category A, score 6.0): `wfv = $16.60`, `mos_threshold = $13.28`, `current_price = $16.32`. Undervaluation vs fair value = +1.74% (marginally below fair value), but above the 80% MOS threshold. Correctly NO ENTRY.

FSLY is the one name in Diamond+Strong where a modest price pullback would flip it to ENTRY. Not actionable today, but worth noting for monitoring.

---

## JSONL Audit Event Coverage

Per acceptance criteria (4 in README):

- `stage3_run_start`: 1 ✅
- `stage3_symbol_result`: 21 (one per processed symbol) ✅
- `stage3_cascade_decision`: 2 (one per tier boundary) ✅ — this event type was not in the original spec but is a correct addition; logged after Diamond and after Strong
- `stage3_run_complete`: 1 ✅

JSONL accurately reflects run behavior. Cascade log says "continue" after both Diamond and Strong, matching CSV contents.

---

## Regression Test Coverage

64 tests pass (0 failures, 0 errors). Tests added this cycle:

- `test_load_sec_companyfacts_uses_revenue_tag_fallbacks` (3 subtests: Revenues, SalesRevenueNet, IncludingAssessedTax)
- `test_load_sec_companyfacts_prefers_annual_revenue_over_quarterly_tag_hit`
- `test_stage3_share_sanity_allows_low_implied_valuation`
- `test_stage3_share_sanity_still_fails_high_implied_valuation`
- 11 tests in `test_stage3_runner.py` covering cascade, isolation, sort, kill propagation, column aliases

Coverage is adequate for the fixes made. LOW-3 tag gaps (UEC/SOC) will need tests when addressed.

---

## Next Required Action

Diamond+Strong yielded **0 actionable names** (threshold: 5). Per cascade logic, Standard tier (27 symbols) must now be processed.

**Command to run:**

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Standard
```

Run Standard in isolation first. If Standard yields ≥5 actionable, cascade stops. If Standard still returns 0, run Watch (17 symbols) next.

If all four tiers complete and actionable count remains 0, that is a valid sieve result for current market conditions. Do not tune thresholds to manufacture entries. Stop the run and document it.

**Important:** Pull latest `stages/stage2/output/Stage2_Report.csv` from git before running. The local file may still be the offline run (21 Diamond names). The live run has 6 Diamond names. Use the git version.

---

## Summary Table

| Component | Status | Notes |
|-----------|--------|-------|
| BUG-1 revenue tag fallback | ✅ GREEN | Correct implementation + tests |
| BUG-2 directional share sanity | ✅ GREEN | Correct at both code locations + tests |
| Full test suite | ✅ GREEN | 64 passed, 3 subtests |
| JSONL audit coverage | ✅ GREEN | All required event types present |
| CSV sort order | ✅ GREEN | Verified against output |
| QC FAIL isolation | ✅ GREEN | 5 QC FAILs, all with reason strings, no silent drops |
| stage2_kills propagation | ✅ GREEN | No false DIAMOND upgrades in output |
| Negative MOS (GLXY, RIOT) | ⚠️ WATCH-1 | Correct behavior, confusing output — log as LOW-3 for v2 |
| Revenue tag gap (UEC, SOC) | ⚠️ WATCH-2 | Expected gap for mining/energy tags — log as LOW-3 for v2 |
| 0 actionable Diamond+Strong | 🔄 CONTINUE | Cascade to Standard required |
