# Stage 1 Mission

Stage 1 is the mechanical market narrowing stage. It must be deterministic, auditable, and boring.

## Step 1 contract

Stage 1 / Step 1 performs the U.S. market information pull and rough mechanical filter:

1. Start from broad U.S. market information.
2. Keep only symbols with market cap `>= $1B`.
3. Keep only symbols with price proxy between `$10` and `$75` inclusive.
4. Keep only symbols with share volume `>= 1,000,000`.
5. Write a stable rough survivor CSV for the next Stage 1 step.

This step is not allowed to use premium, valuation, sentiment, or qualitative business judgment.

## Step 2 contract

Stage 1 / Step 2 consumes the Step 1 rough survivor CSV and splits it into exactly two enrichment batches:

1. `NYSE.csv`
2. `NASDAQ.csv`

The split is only an operational batching aid for enrichment. It must preserve all Step 1 survivors and must report any unknown exchange rows instead of silently dropping them.

## Step 3 contract

Stage 1 / Step 3 enriches the Step 2 exchange batches from Barchart:

1. Call Barchart once per stock in each exchange CSV.
2. Fill every supported Barchart field captured by the parser.
3. Review required enrichment fields after the first pass.
4. Retry only rows with missing required fields.
5. Stop after no more than two repair rounds.
6. Keep retry and unresolved rows visible in CSV outputs and audit logs.

This step is a data collection/enrichment step only. It should not silently drop symbols or turn a missing Barchart field into a trade-quality verdict.

## Step 4 contract

Stage 1 / Step 4 completes the mechanical Stage 1 output:

1. Merge `NASDAQ_barchart_enriched.csv` and `NYSE_barchart_enriched.csv` back into one enriched CSV.
2. Parse `barchart_implied_volatility` as the final premium gate.
3. Pass only rows with implied volatility `>= 75`.
4. Fail rows below `75` or rows missing implied volatility, with an explicit fail reason.
5. Write the merged CSV, `Stage1_PASS.csv`, `Stage1_FAIL.csv`, and a JSONL audit event.
6. Copy the completed `Stage1_PASS.csv` into `stages/stage2/input/Stage1_PASS.csv`.

This is still a mechanical filter. It does not make valuation, sentiment, or business-quality judgments.
