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

## Step 4 completed output

Module: `stages.stage1.code.step4_complete_stage1_output`

Purpose:

- Consume the Step 3 Barchart-enriched NASDAQ and NYSE CSVs.
- Merge both exchanges back into one enriched Stage 1 CSV.
- Apply the final Stage 1 implied-volatility floor of `>= 75`.
- Write `Stage1_PASS.csv` and `Stage1_FAIL.csv` with explicit verdict/fail-reason fields.
- Append a JSONL audit event.
- Copy the completed pass CSV into `stages/stage2/input/Stage1_PASS.csv`.

Run:

```bash
python -m stages.stage1.code.step4_complete_stage1_output \
  --input-dir stages/stage1/output/barchart_enrichment \
  --output-dir stages/stage1/output \
  --stage2-input-dir stages/stage2/input \
  --audit-log stages/stage1/audit_logs/stage1_step4_complete_output.jsonl \
  --min-implied-volatility 75
```
