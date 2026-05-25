# Stage 3 Mission

**Stage:** 3 of 3 (pre-trade)
**Role:** Fundamental valuation filter — determines whether a surviving Stage 2 name is worth owning at its current price.

---

## What Stage 3 Decides

Stage 2 answers: *Is this stock behaving correctly as an options premium vehicle?*
Stage 3 answers: *Would I actually want to own this stock if assigned?*

For the Wheel strategy, this is the critical backstop. Selling a cash-secured put means accepting potential assignment. Stage 3 ensures that every name that reaches a trade decision has been evaluated on whether its fundamentals justify ownership at or below the put strike price. A high-IV name with broken fundamentals is a premium trap, not an opportunity.

Stage 3 does **not** select strikes, calculate premium yield, or make final trade decisions. That is the responsibility of the downstream trade construction layer. Stage 3's sole job is to answer the fundamental question: pass or no entry.

---

## Inputs

- `stages/stage2/output/Stage2_Report.csv` — the full Stage 2 sieve output
- Live price at time of Stage 3 run (fetched fresh per symbol via Finviz)
- SEC EDGAR companyfacts API — fundamental spine (revenue, FCF, operating income, cash, shares)

Stage 3 does **not** re-fetch Barchart data. Finviz is re-fetched only for a current price snapshot.

---

## Method

A 5-year discounted cash flow model with bear/realistic/bull scenarios and a weighted fair value output. Two model variants:

- **Category A** (profitable or FCF-positive): 10% discount rate, 80% MOS threshold, realistic-weighted scenario mix (25/50/25)
- **Category B** (pre-profitable / burning cash): 15% discount rate, 50% MOS threshold, pessimistic-weighted scenario mix (42/46/12)

APLD receives a bespoke forward buildout EV model (see `screener.py: _apld_forward_buildout_stage3`) due to its infrastructure development lifecycle.

---

## Output Verdicts

Exactly four legal verdict labels:

| Verdict | Meaning |
|---|---|
| `DIAMOND` | Price <= MOS threshold, zero Stage 2 kills |
| `ENTRY` | Price <= MOS threshold, 1-2 Stage 2 kills |
| `NO ENTRY` | Price above MOS threshold, or Stage 1/2 disqualified |
| `QC FAIL` | SEC data unavailable, share denominator sanity failed, or zero/missing revenue |

**Important:** These labels are independent of Stage 2 tier names (Diamond/Strong/Standard/Watch/Eliminated).
A Stage 2 Diamond tier name can come back as Stage 3 NO ENTRY if the stock is currently overvalued relative
to its DCF fair value. That is not a contradiction — it means the HP sieve liked the name's behavior but
the fundamentals do not support ownership at today's price.

---

## Outputs

- `stages/stage3/output/Stage3_Report.csv` — per-symbol verdicts with full valuation detail
- `stages/stage3/audit_logs/stage3_run_<timestamp>.log` — human-readable run log
- `stages/stage3/audit_logs/stage3_run_<timestamp>.jsonl` — machine-readable audit events

---

## Acceptance Criteria for a Valid Stage 3 Run

1. All eligible symbols (non-Eliminated from Stage 2) are processed unless cascade stops early
2. Zero unhandled exceptions — errors produce QC FAIL verdicts, not crashes
3. Output CSV is sorted by Stage 2 tier order (Diamond -> Strong -> Standard -> Watch), then by stage2_score descending within tier
4. Audit JSONL contains one event per symbol plus a run summary event
5. DIAMOND + ENTRY count is credible: if all processed names return NO ENTRY or QC FAIL, stop and investigate

---

## What Stage 3 Does NOT Do

- Strike selection or DTE analysis
- Premium yield calculation
- Earnings date clearance checks
- Portfolio position context or current holdings awareness
- Final trade recommendation

All of the above belong in the downstream trade construction and AI confirmation layer,
which requires current position data that Stage 3 does not have access to.
