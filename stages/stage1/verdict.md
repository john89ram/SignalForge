# Stage 1 Verdict

Stage 1 is mechanically complete for the current checked universe and now matches the prior known-good Stage 1 pass set.

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
- Step 4 options-liquidity enrichment is implemented and run.
  - Input rows: 757
  - Cache-hit rows during legacy reconciliation run: 748
  - Live-fetched rows during legacy reconciliation run: 9
  - Missing liquidity rows after enrichment: 9
  - It writes `stage1_step4_options_liquidity_enriched.csv` and `stage1_step4_options_liquidity_enrichment.jsonl`.
- Step 5 completed Stage 1 output is implemented and run.
  - Merged enriched rows: 757
  - Final Stage 1 PASS rows: 71
  - Final Stage 1 FAIL rows: 686
  - Final gates: `barchart_implied_volatility >= 75`, `options_volume >= 1,000`, `open_interest >= 1,000`, and market cap `>= $1B` using legacy cache market cap when present.
  - Reconciliation against the uploaded old Stage 1 files: PASS symbol sets match exactly; no new extras and no missing old pass names.
  - It writes `Stage1_PASS.csv`, `Stage1_FAIL.csv`, a merged audit CSV, a JSONL audit event, and a Stage 2 input copy.

## Current verdict

Stage 1 is now a deterministic mechanical funnel:

1. Raw local market archive -> rough $1B / $10-$75 / 1M-volume filter.
2. Rough survivors -> exchange batches.
3. Exchange batches -> Barchart enrichment with bounded repair.
4. Barchart-enriched rows -> options-liquidity enrichment.
5. Liquidity-enriched rows -> final IV / options-volume / open-interest / market-cap filter and Stage 2 handoff.

The completed Stage 1 handoff artifact is:

`stages/stage2/input/Stage1_PASS.csv`

Rows that fail the final gates, or rows where required final-gate fields are missing, are retained in:

`stages/stage1/output/Stage1_FAIL.csv`
