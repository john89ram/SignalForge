# Stage 3 DCF Engine Redesign — Operator Brief

**Date:** 2026-05-25  
**Author:** Hermes Gatekeeper (Auditor)  
**Status:** MANDATORY — replaces existing `stage3_analysis()` valuation engine  
**Priority:** BLOCKER — current output is not credible; cascade to Standard is on hold pending this fix

---

## The Problem

The current `stage3_analysis()` function uses a **5-year FCF DCF** model. For Category B pre-profitable names, this model is fundamentally wrong and produces absurd per-share values.

**Evidence from live Diamond+Strong run:**

| Symbol | Analyst 1-yr Target | Current Price | Pipeline WFV | Pipeline MOS | Verdict |
|--------|--------------------|-----------|----|---|---------|
| MARA | $15.50 | $13.81 | $1.28 | $0.64 | NO ENTRY |
| CLSK | $21.50 | $15.97 | $1.00 | $0.50 | NO ENTRY |
| QUBT | $18.00 | $12.31 | $1.14 | $0.57 | NO ENTRY |
| USAR | $35.00 | $25.30 | $8.02 | $4.01 | NO ENTRY |
| GLXY | $42.50 | $28.65 | -$68.22 | -$34.11 | NO ENTRY |
| RIOT | $25.00 | $24.49 | -$0.24 | -$0.12 | NO ENTRY |

IONQ was run separately. The pipeline produced WFV = $1.16. The correct EV/Revenue analysis (Hermes-mini manual overlay, stored in `audit_logs/misses/`) produced WFV = $35.61. A 30× discrepancy.

Hermes-mini explicitly confirmed the pipeline model is "too punitive for [IONQ] because it values today's negative FCF path almost mechanically."

**Why the FCF model fails for Category B:**

The bear scenario for Category B uses FCF margins of `[-0.60, -0.45, -0.35, -0.28, -0.20]` — all deeply negative, no terminal value. For a company with $58.7M revenue, this produces 5 years of negative cash flows. The only thing keeping equity positive is the cash balance. Divide the cash by share count and you get ~$1-2/share regardless of what the business actually does.

This is not a valuation. It is a liquidation estimate with a revenue multiple of zero.

The operator-provided **STAGE3_CHEAT_SHEET.md** (stored in `audit_logs/misses/stage3_reports/`) is the authoritative methodology. It specifies:

> **Category A:** EV/EBITDA on forward estimates, 25/50/25 weights  
> **Category B:** EV/EBITDA or EV/Revenue on 3-year forward, 38–40% / 45–47% / 13–17% weights  
> **Construction-phase names (APLD-type):** Forward buildout EV — already implemented correctly

The 5-year FCF DCF is not in the cheat sheet. It must be replaced.

---

## The Fix — Full Implementation Spec

### What Already Works (Do Not Touch)

- `_apld_forward_buildout_stage3()` — already uses EV/EBITDA forward buildout model. Correct. Leave it alone.
- `stage3_share_count()` — correct.
- `load_sec_companyfacts()` — correct after BUG-1 fix.
- `summary_verdict()` — correct.
- Category classification logic (op_cf > 0 OR op_income > 0 → Category A) — correct.
- QC FAIL paths (missing revenue, share QC) — correct.
- Directional share sanity check (upside_delta > 0.20) — correct, keep it.
- Scenario weights: already correct for Cat A (25/50/25). Category B needs small adjustment (see below).

### What Must Change

Replace the `project()` inner function and everything below it in `stage3_analysis()` with the new valuation engine described below.

---

### Category B — 3-Year Forward EV/Revenue Model

**Why 3-year forward:** These are growth companies. Their current revenue understates forward reality. A 3-year projection captures the first leg of growth without requiring heroic 10-year assumptions. It is directionally honest.

**Why EV/Revenue instead of EV/EBITDA:** Most Category B names have negative or near-zero EBITDA. Applying a multiple to a negative number produces a negative EV. Use EV/Revenue as the primary multiple. Future improvement: add EV/EBITDA support when projected EBITDA turns positive.

**Revenue projections by scenario:**

```python
# Growth floors prevent negative-trailing-growth names from bottoming out
# Even a declining business (MARA: -25% last year) should project some recovery
# for the forward period — Stage 2 quality gates already confirmed the name is alive

BULL_CAGR  = clamp(growth * 1.50, 0.35, 2.50)   # at least 35% per year for 3 yrs
REAL_CAGR  = clamp(growth * 1.00, 0.15, 1.50)   # at least 15% per year for 3 yrs
BEAR_CAGR  = clamp(growth * 0.50, 0.05, 0.80)   # at least 5% per year for 3 yrs

y3_bull_rev  = revenue * (1 + BULL_CAGR) ** 3
y3_real_rev  = revenue * (1 + REAL_CAGR) ** 3
y3_bear_rev  = revenue * (1 + BEAR_CAGR) ** 3
```

**EV/Revenue multiples:**

| Scenario | Multiple | Rationale |
|----------|----------|-----------|
| Bear | 1.5× | Growth deceleration, market de-rates the name |
| Realistic | 4.0× | Moderate growth premium for high-IV speculative names |
| Bull | **use `q.target_price` directly if available** | Analyst consensus IS the market's bull case |

The `q.target_price` field is already populated from the live Finviz fetch. It requires no additional plumbing. Use it.

**Bull scenario logic:**
```python
if q.target_price is not None and q.target_price > 0:
    bull = float(q.target_price)          # analyst 1-yr target = bull per-share value
    bull_from_analyst = True
else:
    bull = max((y3_bull_rev * 8.0 + (cash or 0.0)) / shares, 0.0)
    bull_from_analyst = False
```

**Realistic and Bear:**
```python
realistic = max((y3_real_rev * 4.0 + (cash or 0.0)) / shares, 0.0)
bear      = max((y3_bear_rev * 1.5 + (cash or 0.0)) / shares, 0.0)
```

**Important: floor per-share at zero.** An equity value can be negative if EV < 0, but per-share output should not be negative — it is already captured by the NO ENTRY verdict.

**Scenario weights (adjust from current 42/46/12):**
```python
weights = {"bear": 0.40, "realistic": 0.46, "bull": 0.14}
```
This aligns with the cheat sheet range (38–40 / 45–47 / 13–17). The current 42/46/12 over-weights bear and under-weights bull slightly. Use 40/46/14.

**MOS threshold:** Keep at 50% for Category B. Correct per cheat sheet.

---

### Category A — 1-Year Forward EV/EBITDA Model

**EBITDA proxy:** Use `op_income` as the EBITDA proxy (missing D&A, but within 15-25% for most names — acceptable for scenario modeling). Fall back to `net_income` if op_income unavailable.

**Forward projection:** Apply a 1-year forward growth rate per scenario to the trailing EBITDA proxy.

```python
ebitda_proxy = op_income if op_income is not None else net_income
# If ebitda_proxy is None or <= 0, fall back to FCF proxy margin approach
# (Category A QC should catch truly broken names)

if ebitda_proxy and ebitda_proxy > 0:
    bull_ebitda  = ebitda_proxy * (1 + clamp(growth * 1.20, 0.10, 0.50))
    real_ebitda  = ebitda_proxy * (1 + clamp(growth * 1.00, 0.05, 0.35))
    bear_ebitda  = ebitda_proxy * (1 + clamp(growth * 0.70, 0.00, 0.25))

    bull      = max((bull_ebitda * 18 + (cash or 0.0)) / shares, 0.0)
    realistic = max((real_ebitda * 14 + (cash or 0.0)) / shares, 0.0)
    bear      = max((bear_ebitda * 10 + (cash or 0.0)) / shares, 0.0)
else:
    # Negative EBITDA Category A (SBC-heavy, OCF-positive): use FCF proxy approach
    # This keeps the old behavior only for the edge case where op_income is negative
    # but op_cf is positive (meaning D&A/SBC inflates OCF vs EBITDA).
    # Retain existing project() logic here as the fallback.
    pass
```

**Standard Category A probability weights:** 25/50/25 — already correct, keep them.

**MOS threshold:** Keep at 80% for Category A. Correct per cheat sheet.

---

### Output Dict — Add These Fields

Emit two new fields in the return dict so the output CSV and auditor logs capture the methodology:

```python
"valuation_method": "ev_revenue_3yr" if category == "B" else "ev_ebitda_1yr",
"bull_from_analyst_target": bull_from_analyst,  # True if q.target_price was used for bull
```

Add `bull_from_analyst_target` to the Stage3_Report.csv output columns too (in `run_stage3.py`). This makes it clear in the output which names used analyst targets vs model-derived bulls.

---

### Updated Watch Signals

The current generic watch signals violate the cheat sheet. Replace them with data-driven signals that at least reference the specific metric in play:

**Category B watch signal logic:**
```python
# Derive from available data rather than a static string
cash_runway = None
if cash and op_cf and op_cf < 0:
    cash_runway = cash / abs(op_cf)  # years

if cash_runway and cash_runway < 2.0:
    watch_signal = (
        f"Cash runway critical: {cash_runway:.1f} yrs at current burn — "
        f"next capital raise or path to cash-flow breakeven required within 12 months"
    )
elif prev_revenue and revenue < prev_revenue:
    yoy_decline = (revenue / prev_revenue - 1) * 100
    watch_signal = (
        f"Revenue declining ({yoy_decline:+.0f}% YoY) — "
        f"reversal required in next 2 quarters to sustain Category B classification"
    )
else:
    watch_signal = (
        "Next revenue step-down below 50% YoY growth OR cash runway drops under 18 months"
    )
```

**Category A watch signal:** Keep existing "Close below the 50-day SMA by 5% on elevated volume" for now — Category A names are not the priority.

---

### Regression Test Requirements

Update `tests/test_stage3_runner.py` and `tests/test_screener.py` to cover:

1. **`test_category_b_uses_ev_revenue_not_fcf`** — assert that for a Category B name with negative op_cf, the returned `valuation_method` is `"ev_revenue_3yr"` and `weighted_fair_value` is not driven by tiny FCF NPV.

2. **`test_category_b_bull_uses_analyst_target`** — mock a QuoteSnapshot with `target_price = 20.0` and assert `bull == 20.0` and `bull_from_analyst_target == True`.

3. **`test_category_b_bull_fallback_when_no_analyst_target`** — mock `target_price = None`, assert `bull_from_analyst_target == False` and bull is derived from EV/Revenue.

4. **`test_category_b_growth_floor_applied`** — provide a name with `-40%` historical revenue growth (below the clamp). Assert realistic scenario uses at least 15% CAGR floor, not -25%.

5. **`test_category_b_per_share_floors_at_zero`** — construct a scenario where EV would be negative. Assert `bear >= 0.0` and no negative per-share values in output.

6. **`test_category_a_uses_ev_ebitda`** — assert `valuation_method == "ev_ebitda_1yr"` for a Category A name with positive op_income.

Existing tests must still pass. The new tests verify the new methodology, not the old one.

---

## Expected Output After Fix

Running the Diamond tier with the new engine, expected characteristics:

| Symbol | Old WFV | Expected New WFV Range | Notes |
|--------|---------|------------------------|-------|
| MARA | $1.28 | $3–5 (WFV), $15.50 bull anchor | Analyst target used as bull |
| CLSK | $1.00 | $2–4 | Same |
| QUBT | $1.14 | $3–6 | Same |
| USAR | $8.02 | $8–15 | Higher EV/Rev + analyst anchor |
| GLXY | -$68.22 | Should be positive | EV/Revenue eliminates negative FCF problem |
| RIOT | -$0.24 | Should be positive | Same |

**IMPORTANT: Expect most names to still be NO ENTRY.** These are speculative names trading at a large premium to fundamental value. The point of this fix is to make the WFV credible, not to manufacture ENTRY verdicts. A MARA WFV of $4.50 vs price of $13.81 is still decisively NO ENTRY. The number is just one that can be defended.

If the redesign produces ENTRY verdicts on names that were NO ENTRY, that is not automatically correct — it requires auditor review.

---

## What to Deliver

1. Updated `screener.py` — `stage3_analysis()` function with new Category B and Category A valuation engines
2. Updated `stages/stage3/code/run_stage3.py` — add `bull_from_analyst_target` to output CSV and JSONL
3. Updated `tests/test_screener.py` — 6 new tests covering the methodology change
4. Updated `stages/stage3/code/README.md` — reflect new valuation approach in the spec (brief update, not a full rewrite)
5. A re-run of the Diamond tier with the new engine and the output committed to `stages/stage3/output/`

Do NOT change:
- `_apld_forward_buildout_stage3()` — this is already an EV/EBITDA forward model, it is correct
- `load_sec_companyfacts()` — correct after BUG-1 fix
- `summary_verdict()` — correct
- `stage3_share_count()` — correct
- The directional share sanity check — correct, keep it

---

## Recommended First Run After Fix

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond
```

Verify:
1. GLXY and RIOT no longer produce negative WFV
2. MARA WFV is in the $3-6 range (not $1.28)
3. `bull_from_analyst_target` is True for names where Finviz returned a target price
4. All 6 Diamond tests pass
5. No new QC FAILs introduced by the methodology change

Submit handoff with full run artifacts as usual.
