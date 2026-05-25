# Stage 1 Verdict

Stage 1 is mechanically complete for the current checked universe.

## Completed checkpoints

- Step 1 rough filter is implemented and verified against the current local Nasdaq summary archive.
  - Input rows: 7,575
  - Rough survivors: 757
- Step 2 exchange split is implemented for enrichment batching.
  - NYSE rows: 477
  - NASDAQ rows: 280
  - Unknown exchange rows: 0
- Step 3 Barchart enrichment is implemented and has been run against the full exchange split.
  - Enriched rows: 757
  - Final unresolved required-field rows after two repair rounds: 18
- Step 4 completed Stage 1 output is implemented and run.
  - Merged enriched rows: 757
  - Final Stage 1 PASS rows with `barchart_implied_volatility >= 75`: 121
  - Final Stage 1 FAIL rows: 636
  - Fail reasons: 627 below IV floor; 9 missing implied volatility.
  - It writes `Stage1_PASS.csv`, `Stage1_FAIL.csv`, a merged audit CSV, a JSONL audit event, and a Stage 2 input copy.

## Current verdict

Stage 1 is now a deterministic mechanical funnel:

1. Raw local market archive -> rough $1B / $10-$75 / 1M-volume filter.
2. Rough survivors -> exchange batches.
3. Exchange batches -> Barchart enrichment with bounded repair.
4. Enriched rows -> final implied-volatility filter and Stage 2 handoff.

The completed Stage 1 handoff artifact is:

`stages/stage2/input/Stage1_PASS.csv`

Rows that fail the final implied-volatility floor, or rows where implied volatility is missing, are retained in:

`stages/stage1/output/Stage1_FAIL.csv`
