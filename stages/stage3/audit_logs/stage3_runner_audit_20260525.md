# Stage 3 Runner Audit — Post-Build Review

**Date:** 2026-05-25
**Auditor:** Hermes Gatekeeper
**Scope:** Full review of run_stage3.py, test_stage3_runner.py, first Diamond validation run artifacts
**Commit reviewed:** 29eb69b feat(stage3): add canonical batch runner

---

## Overall Verdict

**Runner (run_stage3.py): GREEN.**
**Valuation output: NOT GREEN — two bugs in screener.py, not in the runner.**

The runner is production-quality. All 11 tests pass (independently verified). The first
Diamond run produced all-QC FAIL results, but this is not a runner failure. The runner
correctly fetched live data, caught errors per-symbol without crashing, and produced
complete CSV/log/JSONL artifacts. The QC FAILs trace to two pre-existing bugs in the
DCF engine (screener.py) that were not visible before live data was run at scale.

---

## Runner Review — GREEN

### What was verified

- All 11 regression tests pass independently
- Cascade logic: stops early when threshold met, continues when below, disabled at 0
- Error isolation: per-symbol exceptions produce QC FAIL rows, run does not abort
- Sort order: tier order → stage2_score descending → symbol ascending
- Alias handling: hp_tier / stage2_bad_text / stage2_weak_text all resolve correctly
- Constructor: TickerAnalysis(symbol, quote, barchart=BarchartSnapshot(), options=OptionsSnapshot())
- Kill propagation: stage2_kills populated from stage2_bad_text before summary_verdict()
- Eligibility guard: checks both tier != Eliminated AND eligible_for_stage3 column
- JSONL events: stage3_run_start / stage3_symbol_result / stage3_cascade_decision / stage3_run_complete all present
- Input tier counts logged at run start (stale CSV detection)
- Offline mode correctly skips live fetches

### One minor note (non-blocking)

`_populate_stage2_state()` sets `analysis.stage2_verdict = row.get("stage2_verdict", "")`.
`stage2_verdict` is not a defined field on the TickerAnalysis dataclass. Python allows this
at runtime and summary_verdict() does not use it, so it causes no errors. Clean it up in
a future pass but do not block on it.

---

## QC FAIL Root Cause Analysis

All six Diamond names returned QC FAIL on the first live run. The causes split into two
distinct bugs in screener.py.

---

## BUG-1 — Revenue tag gap in load_sec_companyfacts()

**File:** screener.py, lines 391–398
**Severity:** HIGH — blocks Stage 3 for a significant portion of the universe
**Affected symbols:** CLSK, PCT, QUBT, USAR (and likely others in Strong/Standard/Watch tiers)

### Root cause

load_sec_companyfacts() searches exactly one revenue XBRL tag:

```python
"RevenueFromContractWithCustomerExcludingAssessedTax": out.revenue,
```

This is the ASC 606 tag. Many companies file under different tags:

- Bitcoin miners (CLSK, MARA): typically use `Revenues`
- Early-stage/small-cap (QUBT, PCT): often use `Revenues` or `SalesRevenueNet`
- Specialty companies (USAR): may use `SalesRevenueNet` or `SalesRevenueGoodsNet`

When the tag is absent, `out.revenue` stays empty. stage3_analysis() then returns:

```python
if not sec or not sec.revenue or q.price is None:
    return qc_fail("SEC data unavailable or no live price")
```

This is a false QC FAIL. The SEC data exists and was fetched — revenue is just filed
under a different tag.

### Fix

Replace the single revenue tag with a priority-ordered fallback in load_sec_companyfacts():

```python
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
```

Iterate the list; take the first tag that returns non-empty data for `out.revenue`.
Leave all other fact tags unchanged — only revenue has this multi-tag problem in practice.

### Expected outcome after fix

CLSK, USAR should produce real DCF results (both are revenue-generating companies).
QUBT and PCT may still QC FAIL on zero or near-zero revenue — they are early-stage and
that is a correct result, not a bug.

---

## BUG-2 — Share sanity check fires bidirectionally

**File:** screener.py, lines 718–727 (APLD model) and 894–903 (generic model)
**Severity:** HIGH — misclassifies overvalued speculative names as data failures
**Affected symbols:** MARA, UUUU

### Root cause

The sanity check is:

```python
delta = abs(implied_mktcap - q.market_cap) / q.market_cap
if delta > 0.20:
    return qc_fail("share denominator sanity failed...")
```

`implied_mktcap = weighted_fair_value * shares`

MARA: implied $0.51B vs actual $5.27B — 90.4% delta → QC FAIL
UUUU: implied $0.25B vs actual $4.51B — 94.4% delta → QC FAIL

In both cases `implied < actual`. This means the DCF values the stock at roughly 10%
of current market price. That is a valuation signal (massively overvalued per DCF),
not a data quality failure. The correct Stage 3 verdict is NO ENTRY.

The sanity check was designed to catch the OPPOSITE direction: when the share count
denominator is inflated, producing an impossibly HIGH per-share fair value
(implied >> actual). Using abs() causes it to also fire when the DCF undervalues,
which is normal behavior for speculative high-IV names trading at large premiums.

### Fix

Make the check directional. Only fire QC FAIL when the DCF overvalues relative to
market cap (the denominator-inflation case):

```python
# Only flag when implied > actual — that is the share denominator inflation direction.
# When implied < actual the stock is overvalued per DCF; let normal MOS comparison
# return NO ENTRY rather than treating it as a data failure.
if implied_mktcap > q.market_cap * 1.20:
    share_qc_detail = (
        f"implied ${implied_mktcap / 1e9:.2f}B vs "
        f"known ${q.market_cap / 1e9:.2f}B ({delta * 100:.1f}%)"
    )
    return qc_fail(
        f"share denominator sanity failed: {share_qc_detail}",
        ...
    )
```

Apply this change at BOTH locations:
- Line ~719: inside _apld_forward_buildout_stage3()
- Line ~895: inside stage3_analysis() generic model

### Expected outcome after fix

MARA and UUUU will produce real DCF output with a weighted_fair_value well below the
current price. summary_verdict() will return NO ENTRY because price > mos_threshold.
That is the correct answer: the DCF does not support ownership at today's price.

---

## Required Actions

| Priority | Item | File | Lines |
|---|---|---|---|
| HIGH | Add revenue tag fallback list | screener.py | load_sec_companyfacts() ~391–398 |
| HIGH | Make share sanity check directional | screener.py | ~719–727 and ~895–903 |

---

## After Fixes — Expected First Run Behavior

Re-run Diamond tier after both fixes. Expected results:

| Symbol | Expected outcome | Reason |
|---|---|---|
| CLSK | Real DCF result (likely NO ENTRY) | Revenue-generating Bitcoin miner, trades at premium to DCF |
| MARA | NO ENTRY | Share sanity check directional fix; DCF will undervalue vs market price |
| PCT | Possibly still QC FAIL | Near-zero revenue early-stage; correct result |
| QUBT | Possibly still QC FAIL | Near-zero revenue quantum startup; correct result |
| USAR | Real DCF result | Revenue-generating company; tag fix should resolve |
| UUUU | NO ENTRY | Share sanity check directional fix; uranium developer premium |

If Diamond tier still yields 0 actionable (DIAMOND + ENTRY) after fixes, that is a
valid result — it means the 6 Diamond-tier names are overvalued relative to DCF
fundamentals. Cascade to Strong tier and continue.

---

## Regression Test Requirement

After implementing both screener.py fixes, add tests to tests/test_screener.py:

1. test_revenue_tag_fallback_revenues — mock SEC API response with only `Revenues` tag;
   assert load_sec_companyfacts() populates out.revenue correctly.

2. test_revenue_tag_fallback_sales_revenue_net — same with `SalesRevenueNet`.

3. test_share_sanity_check_undervaluation_not_qc_fail — mock a TickerAnalysis where
   DCF weighted_fair_value is 10% of market cap; assert stage3_analysis() returns a
   result dict with NO ENTRY verdict path (not QC FAIL).

4. test_share_sanity_check_overvaluation_is_qc_fail — mock where implied_mktcap is
   200% of actual market cap; assert QC FAIL is still returned (denominator inflation).

---

## Final Note

The runner is solid. Hermes built it correctly and the first-run artifacts are clean.
The QC FAILs are useful findings — they surfaced two real bugs in the DCF engine that
would have caused the same failures for any method of calling stage3_analysis().
Fix screener.py, re-run Diamond, deliver the results.
