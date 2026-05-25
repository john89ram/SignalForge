# Stage 3 Dev Response — README Revision 2 Review

**Timestamp (UTC):** 2026-05-25T20:25:23Z  
**Author:** Hermes  
**Audience:** Senior Dev, Code Auditor  
**Subject:** Response for Dev review before Stage 3 runner implementation  
**Related review doc:** `stages/stage3/audit_logs/stage3_readme_revision2_review_20260525T201403Z.md`  
**Related review commit:** `f8e53fa docs(stage3): review readme revision 2 notes`

---

## Hermes Review Response — Stage 3 README Revision 2

I reviewed the updated `stages/stage3/code/README.md` from commit:

```text
f630c6a audit(stage3): correct build spec column names after Hermes handoff review
```

I also pushed a full review note here:

```text
stages/stage3/audit_logs/stage3_readme_revision2_review_20260525T201403Z.md
```

Review commit:

```text
f8e53fa docs(stage3): review readme revision 2 notes
```

---

## Summary

Revision 2 is a strong improvement and correctly addresses the previous schema mismatch between the Stage 3 build spec and the actual Stage 2 output.

The README now correctly documents that the live Stage 2 CSV uses:

- `hp_tier`, not `stage2_tier`
- `stage2_bad_text`, not `stage2_kills`
- `stage2_weak_text`, not `stage2_flags`
- `price_proxy` as reference-only, not MOS pricing input

I verified the current committed Stage 2 artifact after `git pull`:

```json
{
  "rows": 71,
  "tier_counts": {
    "Diamond": 6,
    "Strong": 15,
    "Standard": 27,
    "Watch": 17,
    "Eliminated": 6
  },
  "verdict_counts": {
    "PASS": 65,
    "ELIMINATED": 6
  },
  "has_hp_tier": true,
  "has_stage2_bad_text": true,
  "has_stage2_kills": false,
  "has_stage2_tier": false
}
```

So the revised README is directionally correct and should be used as the implementation guide.

---

## Blocking correction before implementation

There is one critical issue in the README sample code.

Current sample:

```python
analysis = TickerAnalysis(symbol=symbol, quote=q)
```

This will fail with the current `screener.py` dataclass because `TickerAnalysis` requires `barchart` and `options` as well.

The implementation should use:

```python
from screener import BarchartSnapshot, OptionsSnapshot

analysis = TickerAnalysis(
    symbol=symbol,
    quote=q,
    barchart=BarchartSnapshot(),
    options=OptionsSnapshot(),
)
```

If the current README sample is copied directly into `run_stage3.py`, Stage 3 will crash on the first symbol before reaching SEC fetch or DCF analysis.

---

## Recommended README patch

Add these imports to the README import block:

```python
BarchartSnapshot,
OptionsSnapshot,
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

## Warning-level follow-ups

Two additional defensive improvements are recommended:

### 1. Kill parsing should trust parsed text when `stage2_bad_count` is absent

Current logic is safe for today’s CSV because `stage2_bad_count` exists. But if a future alias-style CSV has `stage2_kills` text and no `stage2_bad_count`, the current sample could silently zero out `analysis.stage2_kills`.

Recommended implementation approach:

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
    analysis.stage2_kills = parsed_kills if len(parsed_kills) >= bad_count else ["kill"] * bad_count
else:
    analysis.stage2_kills = []
```

### 2. Eligibility filtering should check both tier and `eligible_for_stage3`

Recommended logic:

```python
def _is_stage3_eligible(row: dict) -> bool:
    tier = _get_tier(row)
    eligible_text = str(row.get("eligible_for_stage3", "TRUE")).strip().upper()
    eligible = eligible_text not in {"FALSE", "0", "NO", "N"}
    return tier != "Eliminated" and eligible
```

---

## Final verdict

Revision 2 is approved as the implementation direction **after correcting the `TickerAnalysis` constructor sample**.

The schema fixes, alias helpers, cascade logging, JSONL event model, and expanded test list are all good. Once the constructor issue is corrected, the Stage 3 runner can be built from this README.

---

## Requested next step for Dev/Auditor

Please review this response and either:

1. Patch `stages/stage3/code/README.md` with the constructor correction and optional defensive improvements, or
2. Confirm the implementation owner will account for these corrections directly in `run_stage3.py`.

Once Dev/Auditor gives green light, Stage 3 runner implementation can proceed.
