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

## Stage 1 / Step 3 — Barchart data enrichment

**Goal:** enrich each exchange batch with Barchart overview data while limiting repeated site calls.

Process:

1. Read `NYSE.csv` and `NASDAQ.csv` from Step 2.
2. Call Barchart once per symbol and write enriched exchange CSVs.
3. Review required Barchart fields for missing values.
4. Retry only incomplete rows.
5. Stop after at most two repair rounds.
6. Write retry and unresolved CSVs plus a JSONL audit event.

Canonical outputs:

- `stages/stage1/output/barchart_enrichment/NYSE_barchart_enriched.csv`
- `stages/stage1/output/barchart_enrichment/NASDAQ_barchart_enriched.csv`
- `stages/stage1/output/barchart_enrichment/barchart_retry_queue.csv`
- `stages/stage1/output/barchart_enrichment/barchart_unresolved.csv`
- `stages/stage1/audit_logs/stage1_step3_barchart_enrichment.jsonl`

Run Step 3:

```bash
python -m stages.stage1.code.step3_barchart_enrichment \
  --input-dir stages/stage1/output/exchange_splits \
  --output-dir stages/stage1/output/barchart_enrichment \
  --audit-log stages/stage1/audit_logs/stage1_step3_barchart_enrichment.jsonl \
  --max-repair-rounds 2 \
  --delay-seconds 0.25
```

For a safe smoke test, add `--limit-per-exchange 2`.

## Stage 1 / Step 4 — completed Stage 1 output

**Goal:** merge the Barchart-enriched exchange CSVs back into one enriched Stage 1 universe, then apply the final implied-volatility floor.

Process:

1. Read `NASDAQ_barchart_enriched.csv` and `NYSE_barchart_enriched.csv` from Step 3.
2. Write a merged enriched CSV for auditability.
3. Keep rows with `barchart_implied_volatility >= 75`.
4. Write explicit pass/fail CSVs with Step 4 verdict fields.
5. Append a JSONL audit event.
6. Copy `Stage1_PASS.csv` into the Stage 2 input folder.

Canonical outputs:

- `stages/stage1/output/stage1_step4_merged_barchart_enriched.csv`
- `stages/stage1/output/Stage1_PASS.csv`
- `stages/stage1/output/Stage1_FAIL.csv`
- `stages/stage1/audit_logs/stage1_step4_complete_output.jsonl`
- `stages/stage2/input/Stage1_PASS.csv`

Run Step 4:

```bash
python -m stages.stage1.code.step4_complete_stage1_output \
  --input-dir stages/stage1/output/barchart_enrichment \
  --output-dir stages/stage1/output \
  --stage2-input-dir stages/stage2/input \
  --audit-log stages/stage1/audit_logs/stage1_step4_complete_output.jsonl \
  --min-implied-volatility 75
```
