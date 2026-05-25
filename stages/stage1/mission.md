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
