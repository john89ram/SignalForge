# Hermes Response — Stage 3 Runner Audit

**Timestamp (UTC):** 2026-05-25T20:54:51Z  
**Author:** Hermes  
**Audience:** Senior Dev, Code Auditor  
**Audit reviewed:** `stages/stage3/audit_logs/stage3_runner_audit_20260525.md`  
**Audit commit reviewed:** `d6cf415 audit(stage3): runner audit and screener.py fix brief for Hermes`  
**Runner commit audited:** `29eb69b feat(stage3): add canonical batch runner`

---

## Summary response

I reviewed the auditor's post-build notes and independently checked the relevant runner behavior, `screener.py` code paths, tests, and live SEC companyfacts tag availability.

I agree with the audit's main conclusion:

- **Stage 3 runner:** GREEN.
- **First Diamond valuation output:** NOT GREEN yet, due to `screener.py` Stage 3 valuation/source issues, not due to the runner.
- **Next engineering step:** fix `screener.py` under TDD, then re-run the Diamond tier and publish updated artifacts.

The auditor's two high-priority findings are accepted:

1. Revenue tag coverage in `load_sec_companyfacts()` is too narrow.
2. Share sanity check is currently bidirectional and incorrectly converts extreme overvaluation into `QC FAIL` instead of `NO ENTRY`.

One minor correction: the audit's non-blocking note says `stage2_verdict` is not defined on `TickerAnalysis`. In the current `screener.py`, `TickerAnalysis` **does** define `stage2_verdict: str = ""`, so the runner assignment is valid and does not need cleanup for that reason.

---

## Independent verification performed

### Test verification

I re-ran the relevant test groups after pulling the auditor commit:

```text
pytest tests/test_stage3_runner.py tests/test_screener.py -q
```

Result:

```text
25 passed in 0.13s
```

This confirms the current runner and existing screener tests are still green before remediation.

### Code-path verification

I inspected the relevant `screener.py` paths:

- `load_sec_companyfacts()` currently maps only one revenue tag into `out.revenue`:

```python
"RevenueFromContractWithCustomerExcludingAssessedTax": out.revenue,
```

- Generic `stage3_analysis()` uses the bidirectional share sanity check:

```python
delta = abs(implied_mktcap - q.market_cap) / q.market_cap
if delta > 0.20:
    return qc_fail(...)
```

- `_apld_forward_buildout_stage3()` has the same bidirectional check.

The audit is correct that the share sanity guard should protect against denominator inflation in the `implied_mktcap >> market_cap` direction, not against a DCF fair value that is far below current market cap.

### SEC revenue tag verification

I also checked raw SEC companyfacts tag availability for the six Diamond names:

```text
CLSK: RevenueFromContractWithCustomerIncludingAssessedTax, Revenues
PCT:  Revenues
QUBT: RevenueFromContractWithCustomerIncludingAssessedTax, Revenues
USAR: Revenues
MARA: RevenueFromContractWithCustomerExcludingAssessedTax, Revenues
UUUU: RevenueFromContractWithCustomerExcludingAssessedTax, Revenues
```

This supports BUG-1. The current extractor misses real revenue for several names because it only accepts the excluding-assessed-tax ASC 606 tag.

---

## Response to BUG-1 — revenue tag gap

**Status:** Accepted.

The proposed fallback list is appropriate:

```python
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
```

Implementation response:

- Add revenue tag fallback support in `load_sec_companyfacts()`.
- Keep the existing single-tag extraction for net income, operating income, operating cash flow, cash, and shares unless testing reveals a separate issue.
- Add regression tests for at least:
  - `Revenues`
  - `SalesRevenueNet`
  - ideally `RevenueFromContractWithCustomerIncludingAssessedTax` as well, because CLSK/QUBT expose it.

Expected impact:

- CLSK, PCT, QUBT, and USAR should no longer fail simply because `out.revenue` is empty when revenue data exists under another standard tag.
- PCT/QUBT may still correctly fail later if revenue is zero/near-zero or the DCF source contract cannot support valuation. That would be a valid Stage 3 result rather than a source-extraction miss.

---

## Response to BUG-2 — bidirectional share sanity check

**Status:** Accepted.

The audit's interpretation is correct. The current check:

```python
delta = abs(implied_mktcap - q.market_cap) / q.market_cap
if delta > 0.20:
    QC FAIL
```

misclassifies normal DCF overvaluation cases. When:

```text
weighted fair value * shares << current market cap
```

the correct outcome is generally:

```text
NO ENTRY
```

not:

```text
QC FAIL
```

Implementation response:

- Make the sanity check directional in both locations:
  - generic `stage3_analysis()`
  - `_apld_forward_buildout_stage3()`
- Only fire `QC FAIL` when:

```python
implied_mktcap > q.market_cap * 1.20
```

- Preserve the existing diagnostic message and `share_qc_detail` when the high-implied-market-cap path triggers.
- Let low-implied-market-cap cases continue through normal MOS comparison so `summary_verdict()` can return `NO ENTRY`.

Expected impact:

- MARA and UUUU should move from `QC FAIL` to real DCF outputs, likely `NO ENTRY` if the current price remains far above MOS threshold.

---

## Minor correction to auditor note

The audit's one minor runner note says:

> `stage2_verdict` is not a defined field on the TickerAnalysis dataclass.

I checked the dataclass and this is not accurate in the current codebase. `TickerAnalysis` includes:

```python
stage2_verdict: str = ""
```

So this runner line is valid:

```python
analysis.stage2_verdict = row.get("stage2_verdict", "")
```

No cleanup is needed for that specific reason.

---

## Accepted remediation plan

I will implement the `screener.py` fixes using TDD:

1. Add failing tests for SEC revenue tag fallback:
   - `Revenues`
   - `SalesRevenueNet`
   - `RevenueFromContractWithCustomerIncludingAssessedTax`
2. Add failing tests for directional share sanity:
   - low implied market cap vs actual market cap does **not** return `QC FAIL`
   - high implied market cap vs actual market cap still returns `QC FAIL`
3. Patch `load_sec_companyfacts()` revenue extraction.
4. Patch both share sanity checks.
5. Run targeted tests.
6. Run full test suite.
7. Re-run Stage 3 Diamond tier with logs and JSONL.
8. Publish updated `Stage3_Report.csv`, logs, and audit handoff.

---

## Final response

The auditor notes are sound and actionable. I accept the two high-priority `screener.py` fixes as the next required work before Stage 3 valuation output can be considered green.

The Stage 3 runner itself remains green. The next task is valuation-source remediation in `screener.py`, followed by a fresh Diamond validation run.
