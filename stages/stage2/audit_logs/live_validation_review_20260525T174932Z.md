# Stage 2 Live Validation Review

**Run timestamp:** `20260525T174932Z`
**Input:** `stages/stage2/input/Stage1_PASS.csv`
**Output:** `stages/stage2/output/Stage2_Report.csv`
**Runner log:** `stages/stage2/audit_logs/stage2_run_20260525T174932Z.log`
**Audit JSONL:** `stages/stage2/audit_logs/stage2_run_20260525T174932Z.jsonl`
**Operator tee log:** `stages/stage2/audit_logs/stage2_live_validation_20260525T174932Z.operator.log`
**Workers:** 2
**Elapsed:** 262.673 seconds

## Run result

The live Stage 2 validation run completed successfully.

- Input rows: 71
- Output rows: 71
- Per-symbol progress lines in runner log: 71
- Per-symbol progress lines in operator log: 71
- JSONL `stage2_symbol_complete` events: 71
- JSONL `stage2_run_complete` events: 1
- Blank per-test status cells: 0
- Unit/regression tests after run: `50 passed in 0.42s`

## Tier distribution

- Diamond: 6
- Strong: 15
- Standard: 27
- Watch: 17
- Eliminated: 6

## Verdict distribution

- PASS: 65
- ELIMINATED: 6

## Score distribution

- Minimum score: 2.5
- Maximum score: 7.0
- Unique scores: 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0

The score distribution spread across the expected live range instead of clustering at the offline baseline. This supports that live fields were populated and the seven tests were firing.

## Per-test status counts

### IV spike diagnosis

- PASS: 54
- WEAK: 17

### Meme stock

- PASS: 63
- WEAK: 8

### Chart pattern

- PASS: 19
- WEAK: 27
- BAD: 25

### News sentiment

- PASS: 55
- WEAK: 16

### Analyst consensus

- PASS: 34
- WEAK: 16
- BAD: 21

### Liquidity

- PASS: 9
- WEAK: 24
- BAD: 38

### Institutional ownership

- PASS: 41
- WEAK: 12
- BAD: 18

## Auditor-note checks

- Live run did **not** return the offline-looking 71/71 all-PASS shape.
- `InstitutionalOwnershipTest` produced PASS, WEAK, and BAD results; it was not all-SKIP.
- `ChartPatternTest` produced PASS, WEAK, and BAD results; it was not all-PASS.
- News/IV headline-driven tests produced WEAK results.
- Diamond count compressed from the offline baseline to 6, below the auditor's suggested scrutiny threshold of ~15.
- All seven per-test status columns were populated for all 71 rows.

## Stage 3 eligibility note

`Eliminated` names are not eligible for Stage 3. The six eliminated names in this run should be excluded from downstream Stage 3 work unless manually overridden after separate review.

## Production-readiness conclusion

This live run is credible as a Stage 2 validation run. The output differs materially from the offline run, all seven tests emitted populated status fields for every row, and JSONL/log coverage is complete.

Recommended next step: senior/auditor review of `Stage2_Report.csv` plus the JSONL audit file before declaring Stage 2 production-cleared for trading decisions.
