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
