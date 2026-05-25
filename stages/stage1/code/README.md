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
