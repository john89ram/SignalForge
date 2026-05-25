# Project Layout

This repository is organized like a real stage-gated project.

## Canonical stage contract

Every stage has the same five artifacts:

- `mission.md` — what the stage is trying to prove or decide
- `code/` — implementation for that stage
- `output/` — generated artifacts and reports
- `audit_logs/` — run logs, review notes, and evidence
- `verdict.md` — the final decision for that stage

## Top-level structure

```text
market-funnel/
├── docs/
│   └── project-layout.md
├── stages/
│   ├── stage1/
│   │   ├── mission.md
│   │   ├── code/
│   │   ├── output/
│   │   ├── audit_logs/
│   │   └── verdict.md
│   ├── stage2/
│   │   ├── mission.md
│   │   ├── code/
│   │   ├── output/
│   │   ├── audit_logs/
│   │   └── verdict.md
│   └── stage3/
│       ├── mission.md
│       ├── code/
│       ├── output/
│       ├── audit_logs/
│       └── verdict.md
├── tests/
├── runs/
├── screener.py
├── stage2_report.py
└── full_market_pipeline.py
```

## Current code mapping

- **Stage 1**: `screener.py`, `market_cap_census.py`, `nasdaq_market_cap_census.py`
- **Stage 2**: `stage2_report.py`, `exchange_enrichment_workflow.py`
- **Stage 3**: `screener.py` report generation and downstream valuation logic
- **Pipeline orchestration**: `full_market_pipeline.py`

## Review workflow

- Code lives in the stage `code/` folder or is mapped explicitly in the docs.
- Outputs are written to the stage `output/` folder.
- Audit logs are kept with the run that produced them.
- The verdict file is the single place where the stage decision is recorded.
