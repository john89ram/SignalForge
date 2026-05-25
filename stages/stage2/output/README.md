# Stage 2 output

Canonical report:

```text
Stage2_Report.csv
```

The report contains one row per Stage 1 survivor and includes:

- Stage 1 metadata copied through from `Stage1_PASS.csv`
- Stage 2 verdict and Stage 3 eligibility
- HP total, HP remaining, HP damage, and tier
- weak/bad counts and detail text
- per-test status, HP loss, and detail columns for all seven tests

## Committed analysis report

`Stage2_Report.csv` from run `20260525T161635Z` is committed for review/analysis even though generated CSV reports are normally ignored.

Verified report shape:

- Rows: `71`
- Columns: `43`
- Verdict counts: `PASS=71`
- Tier counts: `Diamond=21`, `Strong=38`, `Standard=12`
- Required fields present: `stage2_hp_left`, `stage2_hp_total`, `stage2_score`, `hp_tier`, and all per-test `*_status`, `*_hp_loss`, `*_detail` columns

Generated CSV reports can be recreated from the input CSV and should be reviewed before downstream Stage 3 work.
