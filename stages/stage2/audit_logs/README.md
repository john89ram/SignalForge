# Stage 2 audit logs

Each canonical Stage 2 run writes:

- `stage2_run_<timestamp>.log` — human-readable progress and summary
- `stage2_run_<timestamp>.jsonl` — machine-readable run summary

The JSONL summary includes:

- input CSV path
- output CSV path
- input/output row counts
- tier counts
- verdict counts
- elapsed seconds
- UTC timestamp

Do not hand-edit generated audit logs.
