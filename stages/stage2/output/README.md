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

Generated CSV reports can be recreated from the input CSV and should be reviewed before downstream Stage 3 work.
