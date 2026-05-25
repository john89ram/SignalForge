# Stage 1

Stage 1 is the mechanical front door for SignalForge. It does **not** judge business quality, valuation, sentiment, or trade setup quality. It only prepares a clean, repeatable universe for later stages.

## Stage 1 / Step 1 — U.S. market info grab + rough filter

**Goal:** start from broad U.S. market information and reduce the market to the first rough survivor list.

Canonical filters:

- Market cap: `>= $1,000,000,000`
- Price proxy: `$10 <= price <= $75`
- Volume: `>= 1,000,000`

Source rule:

- Preferred input is the latest raw Nasdaq summary archive CSV: `master_lists/nasdaq_summary_latest.csv`.
- Use `previous_close` as the price proxy because the raw Nasdaq summary archive does not provide a dedicated live price field.

Expected sanity range:

- Raw broad universe: roughly `~10,500` symbols before source/API losses.
- Current local summary archive: `7,575` rows.
- Current rough survivors with the canonical filters: `~750` rows; the checked local archive produces `757`.

Run Step 1:

```bash
python -m stages.stage1.code.step1_rough_filter \
  --input-csv master_lists/nasdaq_summary_latest.csv \
  --output-csv stages/stage1/output/stage1_step1_rough_filter.csv
```

The output CSV is a generated artifact and should feed the next Stage 1 step.

## Stage 1 / Step 2 — exchange split for enrichment batching

**Goal:** split the 757 Step 1 rough survivors into exchange-specific enrichment batches.

Canonical outputs:

- `stages/stage1/output/exchange_splits/NYSE.csv`
- `stages/stage1/output/exchange_splits/NASDAQ.csv`

Run Step 2:

```bash
python -m stages.stage1.code.step2_exchange_split \
  --input-csv stages/stage1/output/stage1_step1_rough_filter.csv \
  --output-dir stages/stage1/output/exchange_splits \
  --audit-log stages/stage1/audit_logs/stage1_step2_exchange_split.jsonl
```

Current checked split:

- NYSE: `477`
- NASDAQ: `280`
- Unknown: `0`

This split is for enrichment throughput and debugging only. It does not change trade eligibility.
