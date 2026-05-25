# Stage2

This stage follows the canonical project contract:

- `mission.md`
- `code/`
- `output/`
- `audit_logs/`
- `verdict.md`

See the files in this folder for the current stage state.

## Input handoff

Stage 2 starts from the completed Stage 1 pass artifact copied by Stage 1 / Step 4:

`stages/stage2/input/Stage1_PASS.csv`

That CSV contains only Stage 1 rows with `barchart_implied_volatility >= 75` and includes Step 4 verdict/audit fields. The current checked Stage 1 handoff contains `121` rows.
