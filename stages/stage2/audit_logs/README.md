# Stage 2 audit logs

Each canonical Stage 2 run writes:

- `stage2_run_<timestamp>.log` — human-readable progress and summary
- `stage2_run_<timestamp>.jsonl` — machine-readable per-symbol events and run summary

The human log includes:

- run metadata: input path, output path, log path, audit JSONL path, row count, worker count, Stage 3 flag, offline-input flag
- one progress line per completed symbol with `completed/total`, percent complete, symbol, tier, verdict, Stage 3 eligibility, HP left/total, damage, weak count, bad count, and error text when applicable
- final `summary=<json>` line

The JSONL audit includes one `stage2_symbol_complete` event per symbol with:

- completed/total counts and percent complete
- input row index and symbol
- tier, verdict, and Stage 3 eligibility
- HP total, HP left, damage, weak count, bad count
- weak/bad detail arrays and error text

The JSONL file ends with a `stage2_run_complete` summary containing:

- input CSV path
- output CSV path
- input/output row counts
- tier counts
- verdict counts
- elapsed seconds
- UTC timestamp

## Committed analysis run

Run ID: `20260525T161635Z`

Committed files:

- `stage2_run_20260525T161635Z.log`
- `stage2_run_20260525T161635Z.jsonl`

Coverage verified for this run:

- Human log: `71` symbol progress lines plus summary
- JSONL audit: `71` `stage2_symbol_complete` events plus `1` `stage2_run_complete` event
- Input rows: `71`
- Output rows: `71`
- Tier counts: `Diamond=21`, `Strong=38`, `Standard=12`
- Verdict counts: `PASS=71`

Do not hand-edit generated audit logs.
