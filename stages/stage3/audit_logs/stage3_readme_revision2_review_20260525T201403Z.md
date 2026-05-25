# Stage 3 README Revision 2 Review

**Timestamp (UTC):** 2026-05-25T20:14:03Z  
**Reviewer:** Hermes  
**Audience:** Senior Dev, Code Auditor  
**Reviewed commit:** `f630c6a audit(stage3): correct build spec column names after Hermes handoff review`  
**Reviewed file:** `stages/stage3/code/README.md`  
**Review type:** Documentation/spec correctness review before implementing `run_stage3.py`

---

## 1. Summary verdict

Revision 2 is a strong improvement over the first Stage 3 build spec. It correctly incorporates the schema mismatch identified in the prior Hermes handoff review and now aligns the Stage 3 runner spec with the actual committed live `Stage2_Report.csv`.

However, I found **one critical implementation-blocking issue in the README sample code** and **one warning-level future-compatibility issue** that should be fixed or consciously handled before implementation starts.

### Review outcome

- **Overall:** Accept with required correction before coding directly from the sample.
- **Blocking issue:** The sample `TickerAnalysis(...)` constructor is invalid for the current `screener.py` dataclass because `barchart` and `options` are required positional fields.
- **Warning:** The kill-count reconstruction logic can fail future alias compatibility if a future CSV has `stage2_kills` text but omits `stage2_bad_count`.
- **Non-blocking:** The rest of the revised schema guidance is sound and should be followed.

---

## 2. What changed in the Dev/Auditor README notes

Pulled latest GitHub state and reviewed commit:

```text
f630c6a audit(stage3): correct build spec column names after Hermes handoff review
```

This commit updates:

```text
stages/stage3/code/README.md
```

The commit message states that Revision 2 corrects the Stage 2 input column names after the Hermes handoff review.

Key changes made by Dev/Auditor:

1. Added a Revision 2 header.
2. Added warning to `git pull` before Stage 3 runs.
3. Replaced proposed Stage 2 columns with actual live Stage 2 columns.
4. Added alias helpers:
   - `_get_tier()`
   - `_get_kills_text()`
   - `_get_flags_text()`
5. Updated `TickerAnalysis` reconstruction guidance.
6. Added `stage3_cascade_decision` JSONL event.
7. Expanded required regression tests from 5 to 10.
8. Added explicit trap list.
9. Updated first-run command to include `git pull`.
10. Added the prior Hermes handoff doc to expected audit log layout.

---

## 3. Verification against actual Stage 2 report

I verified the current committed `Stage2_Report.csv` after `git pull`.

Path:

```text
stages/stage2/output/Stage2_Report.csv
```

Observed shape:

```json
{
  "rows": 71,
  "tier_counts": {
    "Diamond": 6,
    "Eliminated": 6,
    "Standard": 27,
    "Strong": 15,
    "Watch": 17
  },
  "verdict_counts": {
    "ELIMINATED": 6,
    "PASS": 65
  },
  "has_hp_tier": true,
  "has_stage2_bad_text": true,
  "has_stage2_kills": false,
  "has_stage2_tier": false
}
```

This confirms the README Revision 2 correction is directionally correct:

- Actual tier column is `hp_tier`, not `stage2_tier`.
- Actual kill text column is `stage2_bad_text`, not `stage2_kills`.
- Actual weak/flag text column is `stage2_weak_text`, not `stage2_flags`.
- The live Stage 2 tier distribution is the expected 6 / 15 / 27 / 17 / 6 split.

---

## 4. Positive findings

### 4.1 Schema mismatch is now explicitly documented

The README now correctly names the actual Stage 2 columns:

```text
hp_tier
stage2_bad_text
stage2_bad_count
stage2_weak_text
price_proxy
eligible_for_stage3
```

This resolves the biggest risk from Revision 1, where the runner would have looked for non-existent fields and silently reconstructed incorrect Stage 2 state.

### 4.2 Alias boundary is the right design

The README now recommends alias helpers at the CSV parsing boundary:

```python
def _get_tier(row: dict) -> str:
    return row.get("stage2_tier") or row.get("hp_tier", "")

def _get_kills_text(row: dict) -> str:
    return row.get("stage2_kills") or row.get("stage2_bad_text", "")

def _get_flags_text(row: dict) -> str:
    return row.get("stage2_flags") or row.get("stage2_weak_text", "")
```

This is the safest approach. It avoids changing the already-published Stage 2 artifact while keeping Stage 3 forward-compatible if Stage 2 later adds renamed canonical columns.

### 4.3 `stage3_cascade_decision` event is a good addition

Adding a dedicated cascade decision event improves auditability materially.

This should make it clear whether a Stage 3 output contains only Diamond-tier names because the cascade stopped, or because the operator explicitly requested only Diamond.

### 4.4 Regression test list is now appropriately broad

The required tests now cover:

- cascade stopping,
- cascade continuation,
- failure isolation,
- output sort order,
- Stage 2 kill propagation,
- current Stage 2 alias support,
- `--min-verdicts 0`,
- `stage3_analysis()` returning `None`,
- skipping Eliminated rows,
- JSONL event coverage.

This is the right level of test coverage for a runner that will drive valuation decisions.

### 4.5 Fresh price warning is preserved

The README continues to emphasize that `price_proxy` is reference-only and must not drive MOS comparison. That is correct.

Live Stage 3 must fetch fresh Finviz quote data for `q.price` before calling `stage3_analysis()` / `summary_verdict()`.

---

## 5. Critical finding — invalid `TickerAnalysis` constructor in README sample

### Severity

**Critical / implementation-blocking if copied directly.**

### Location

`stages/stage3/code/README.md`, sample reconstruction function around lines 120–153.

Current sample:

```python
analysis = TickerAnalysis(symbol=symbol, quote=q)
```

### Why this is wrong

The actual `TickerAnalysis` dataclass in `screener.py` requires these positional fields:

```python
@dataclass
class TickerAnalysis:
    symbol: str
    quote: QuoteSnapshot
    barchart: BarchartSnapshot
    options: OptionsSnapshot
    ...
```

`barchart` and `options` do **not** have defaults.

Therefore the README sample will raise:

```text
TypeError: TickerAnalysis.__init__() missing 2 required positional arguments: 'barchart' and 'options'
```

### Why this matters

If implementation follows the README sample exactly, the Stage 3 runner will fail on its first symbol before reaching SEC fetch or DCF analysis.

This is not a valuation issue; it is a construction bug in the spec example.

### Recommended correction

The README sample should import `BarchartSnapshot` and `OptionsSnapshot`, then instantiate:

```python
from screener import BarchartSnapshot, OptionsSnapshot

analysis = TickerAnalysis(
    symbol=symbol,
    quote=q,
    barchart=BarchartSnapshot(),
    options=OptionsSnapshot(),
)
```

### Implementation guidance

When building `run_stage3.py`, do not copy the current README constructor line as-is. Use the corrected constructor above.

### Suggested README patch

Add `BarchartSnapshot` and `OptionsSnapshot` to the import list:

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
    stage3_share_count,
    summary_verdict,
    HTTP,
)
```

Then replace:

```python
analysis = TickerAnalysis(symbol=symbol, quote=q)
```

with:

```python
analysis = TickerAnalysis(
    symbol=symbol,
    quote=q,
    barchart=BarchartSnapshot(),
    options=OptionsSnapshot(),
)
```

---

## 6. Warning finding — kill-count alias logic is not fully future-compatible

### Severity

**Warning.** Current live CSV is safe, but the proposed alias behavior can fail for a future schema.

### Location

`stages/stage3/code/README.md`, reconstruction sample around lines 131–140.

Current sample:

```python
bad_text = _get_kills_text(row)
bad_count = int(row.get("stage2_bad_count", 0) or 0)
if bad_text:
    parsed_kills = [k.strip() for k in bad_text.split("|") if k.strip()]
    # Trust the parsed list if count agrees; fall back to count-based placeholder if not
    analysis.stage2_kills = parsed_kills if len(parsed_kills) == bad_count else ["kill"] * bad_count
else:
    analysis.stage2_kills = ["kill"] * bad_count
```

### Why current live CSV is safe

The current live Stage 2 CSV includes both:

- `stage2_bad_text`
- `stage2_bad_count`

So this logic should reconstruct the kill count correctly for today’s committed artifact.

### Why future alias compatibility can fail

The README says the runner should work with both current and future renamed columns. But if a future CSV includes:

```text
stage2_kills = "detail A | detail B"
```

and does **not** include:

```text
stage2_bad_count
```

then:

```python
bad_count = 0
parsed_kills = ["detail A", "detail B"]
len(parsed_kills) != bad_count
analysis.stage2_kills = ["kill"] * 0
```

That silently empties `stage2_kills`, recreating the same bug the alias system was meant to prevent.

### Recommended correction

Use count only when the count column is actually present. If text exists and no count column exists, trust parsed text.

Suggested implementation:

```python
bad_text = _get_kills_text(row)
parsed_kills = [k.strip() for k in bad_text.split("|") if k.strip()] if bad_text else []

raw_bad_count = row.get("stage2_bad_count")
bad_count = int(raw_bad_count) if raw_bad_count not in (None, "") else None

if bad_count is None:
    analysis.stage2_kills = parsed_kills
elif parsed_kills and len(parsed_kills) == bad_count:
    analysis.stage2_kills = parsed_kills
elif bad_count > 0:
    # Preserve the count for summary_verdict() even if text is missing/mismatched.
    analysis.stage2_kills = parsed_kills if len(parsed_kills) >= bad_count else ["kill"] * bad_count
else:
    analysis.stage2_kills = []
```

Alternative, simpler version:

```python
if parsed_kills:
    analysis.stage2_kills = parsed_kills
else:
    analysis.stage2_kills = ["kill"] * bad_count
```

The simpler version is usually sufficient because `stage2_bad_text` should have one pipe-delimited detail per BAD result.

### Test requirement

The existing proposed test `test_current_stage2_column_aliases_are_supported` should be expanded or paired with another test that covers:

- `stage2_kills` present,
- `stage2_bad_count` absent,
- parsed kill details still populate `analysis.stage2_kills`.

---

## 7. Warning finding — `eligible_for_stage3` guard should be explicit

### Severity

**Warning.** The README says `eligible_for_stage3` is a pre-filter guard, but the implementation details mostly emphasize skipping `Eliminated` by tier.

### Why this matters

Today, Stage 2 `Eliminated` rows are the only rows with `eligible_for_stage3=FALSE`. So tier filtering is enough for the current artifact.

But for defensive runner behavior, the Stage 3 input filter should skip rows when either condition says the row is ineligible:

```text
hp_tier == "Eliminated"
```

or

```text
eligible_for_stage3 is false-like
```

### Recommended filter

```python
def _is_stage3_eligible(row: dict) -> bool:
    tier = _get_tier(row)
    eligible_text = str(row.get("eligible_for_stage3", "TRUE")).strip().upper()
    eligible = eligible_text not in {"FALSE", "0", "NO", "N"}
    return tier != "Eliminated" and eligible
```

This prevents future schema drift from sending explicitly-ineligible rows into SEC/Finviz fetches.

---

## 8. Non-blocking note — `git pull required` warning is useful but not sufficient in all cases

### Severity

**Non-blocking / operational note.**

The README now says:

```text
Always run git pull before executing Stage 3 or you will be running against offline data.
```

This is useful and appropriate.

However, for full operator safety, the runner itself should log the input tier distribution at startup. That gives reviewers immediate evidence of whether the run is using the live Stage 2 artifact.

Recommended startup log fields:

```json
{
  "input_rows": 71,
  "eligible_rows": 65,
  "stage2_tier_counts": {
    "Diamond": 6,
    "Strong": 15,
    "Standard": 27,
    "Watch": 17,
    "Eliminated": 6
  }
}
```

If those counts show Diamond=21 / Strong=38 / Standard=12, the operator can immediately stop because they are using the old offline artifact.

This does not need to block implementation, but it should be included in `stage3_run_start` and the human log.

---

## 9. Non-blocking note — import list includes unused symbols

The README import list includes `SECFacts` and `stage3_share_count`.

Those are not harmful, but the runner likely does not need to call `stage3_share_count()` directly because `stage3_analysis()` already handles share QC internally.

No action required. Just avoid adding direct share-count logic to the runner unless a test proves it is necessary.

---

## 10. Accepted implementation guidance from README Revision 2

I agree with these README directions and would follow them when implementing `run_stage3.py`:

1. Reuse existing `stage3_analysis()` and `summary_verdict()`.
2. Do not rewrite the DCF engine.
3. Use current Stage 2 columns and aliases.
4. Fetch fresh Finviz quote for MOS comparison.
5. Fetch SEC companyfacts in live mode.
6. Keep `--workers` default at 2 and do not exceed 3.
7. Convert per-symbol failures into `QC FAIL` rows.
8. Emit `stage3_run_start`, `stage3_symbol_result`, `stage3_cascade_decision`, and `stage3_run_complete` JSONL events.
9. Implement all ten required tests.
10. Run Diamond-only first before expanding tiers.
11. Treat `--offline-input-only` as contract testing only.
12. Keep Stage 3 scoped to ownership valuation, not trade construction.

---

## 11. Recommended action before implementation

Before coding `run_stage3.py`, either patch the README or have the implementer explicitly account for these corrections:

### Must fix / must account for

1. `TickerAnalysis` constructor must include `BarchartSnapshot()` and `OptionsSnapshot()`.
2. Kill parsing should not drop parsed `stage2_kills` text when `stage2_bad_count` is absent.

### Should include in implementation

3. Input eligibility should check both tier and `eligible_for_stage3`.
4. Run-start audit event should include actual input tier counts.

---

## 12. Final review conclusion

The Dev/Auditor README notes are good and incorporate the prior handoff review accurately.

The spec is ready to guide implementation **as long as the constructor issue is corrected**. If someone copies the current sample literally, Stage 3 will fail immediately because `TickerAnalysis` requires `barchart` and `options`.

Once that is corrected, the README Revision 2 is a solid build guide for the Stage 3 runner.
