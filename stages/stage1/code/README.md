# Stage 1 Code

## Step 1 rough filter

Module: `stages.stage1.code.step1_rough_filter`

Purpose:

- Consume the latest broad U.S. market-info CSV.
- Apply the first rough mechanical gates:
  - market cap `>= $1B`
  - price proxy between `$10` and `$75`
  - share volume `>= 1,000,000`
- Write the rough survivor CSV for downstream Stage 1 work.

Run:

```bash
python -m stages.stage1.code.step1_rough_filter \
  --input-csv master_lists/nasdaq_summary_latest.csv \
  --output-csv stages/stage1/output/stage1_step1_rough_filter.csv
```

Notes:

- `previous_close` is the canonical price proxy for the current Nasdaq summary archive.
- The checked local archive produces 757 rough survivors, which matches the expected ~750 sanity range.

## Step 2 exchange split

Module: `stages.stage1.code.step2_exchange_split`

Purpose:

- Consume the Step 1 rough survivor CSV.
- Write `NYSE.csv` and `NASDAQ.csv` for enrichment batching.
- Append a JSONL audit event with counts and output paths.

Run:

```bash
python -m stages.stage1.code.step2_exchange_split \
  --input-csv stages/stage1/output/stage1_step1_rough_filter.csv \
  --output-dir stages/stage1/output/exchange_splits \
  --audit-log stages/stage1/audit_logs/stage1_step2_exchange_split.jsonl
```

Current checked output:

- NYSE: 477 rows
- NASDAQ: 280 rows
- Unknown: 0 rows

## Step 3 Barchart enrichment

Module: `stages.stage1.code.step3_barchart_enrichment`

Purpose:

- Consume the Step 2 exchange split CSVs.
- Call Barchart for every symbol in each split.
- Fill supported Barchart fields:
  - implied volatility
  - historical volatility
  - IV percentile
  - IV rank
  - IV high / low
  - expected move
- Review missing fields after the first pass.
- Retry only incomplete rows, capped at two repair rounds.
- Write enriched, retry queue, unresolved, and audit-log artifacts.

Run:

```bash
python -m stages.stage1.code.step3_barchart_enrichment \
  --input-dir stages/stage1/output/exchange_splits \
  --output-dir stages/stage1/output/barchart_enrichment \
  --audit-log stages/stage1/audit_logs/stage1_step3_barchart_enrichment.jsonl \
  --max-repair-rounds 2 \
  --delay-seconds 0.25
```

Notes:

- `--max-repair-rounds` is capped at 2 to avoid unbounded repeated site calls.
- `--delay-seconds` spaces calls out to reduce stop-out risk.
- `--limit-per-exchange` is available for smoke tests.
- Expected move is captured when Barchart exposes it, but it is not required for completion because many overview pages omit it.

## Step 4 options-liquidity enrichment

Module: `stages.stage1.code.step4_options_liquidity_enrichment`

Purpose:

- Consume the Step 3 Barchart-enriched NASDAQ and NYSE CSVs.
- Merge both exchanges back into one enriched Stage 1 CSV.
- Fill the legacy options-liquidity fields:
  - `options_volume`
  - `open_interest`
  - `atm_bid_ask_spread`
- Support deterministic reconciliation through `--liquidity-cache-csv` inputs.
- Append a JSONL audit event with cache-hit/fetch/missing counts.

Run:

```bash
python -m stages.stage1.code.step4_options_liquidity_enrichment \
  --input-dir stages/stage1/output/barchart_enrichment \
  --output-csv stages/stage1/output/stage1_step4_options_liquidity_enriched.csv \
  --audit-log stages/stage1/audit_logs/stage1_step4_options_liquidity_enrichment.jsonl \
  --delay-seconds 0.25
```

## Step 5 completed output

Module: `stages.stage1.code.step5_complete_stage1_output`

Compatibility wrapper: `stages.stage1.code.step4_complete_stage1_output` remains available for older callers, but new docs and commands should use the Step 5 module name.

Purpose:

- Consume `stage1_step4_options_liquidity_enriched.csv`.
- Apply the final legacy Stage 1 gates:
  - implied volatility `>= 75`
  - options volume `>= 1,000`
  - open interest `>= 1,000`
  - market cap `>= $1B` (`legacy_stage1_market_cap` when present, otherwise current `market_cap`)
- Write `Stage1_PASS.csv` and `Stage1_FAIL.csv` with explicit verdict/fail-reason fields.
- Append a JSONL audit event.
- Copy the completed pass CSV into `stages/stage2/input/Stage1_PASS.csv`.

Run:

```bash
python -m stages.stage1.code.step5_complete_stage1_output \
  --input-dir stages/stage1/output \
  --output-dir stages/stage1/output \
  --stage2-input-dir stages/stage2/input \
  --audit-log stages/stage1/audit_logs/stage1_step5_complete_output.jsonl \
  --min-implied-volatility 75 \
  --min-options-volume 1000 \
  --min-open-interest 1000 \
  --min-market-cap 1000000000
```
