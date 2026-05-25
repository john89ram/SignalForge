# Market Funnel Screener

A local premium-first market screener organized as a stage-gated project.

## Project structure

The repo is split into three stages, each with the same contract:

- `mission.md`
- `code/`
- `output/`
- `audit_logs/`
- `verdict.md`

See [`docs/project-layout.md`](docs/project-layout.md) for the canonical layout.

## Stage map

- **Stage 1** — mechanical premium/liquidity screening
- **Stage 2** — enrichment, verification, and retry logic
- **Stage 3** — deeper review and final verdicting

## Current implementation map

- **Stage 1 code**: `screener.py`, `market_cap_census.py`, `nasdaq_market_cap_census.py`
- **Stage 2 code**: `stage2_report.py`, `exchange_enrichment_workflow.py`
- **Stage 3 / orchestration**: `full_market_pipeline.py`

## Run it

```bash
cd /home/hermes/market-funnel
python screener.py --tickers IONQ,PLTR,NVDA
```

### Output formats

Markdown:
```bash
python screener.py --tickers IONQ,PLTR --output markdown
```

JSON:
```bash
python screener.py --tickers IONQ,PLTR --output json
```

CSV:
```bash
python screener.py --tickers IONQ,PLTR --output csv > report.csv
```

Direct file write:
```bash
python screener.py --tickers IONQ,PLTR --output csv --csv-path report.csv
```

### Universe file

You can also pass a text file with tickers:

```bash
python screener.py --universe universe.txt
```

Format:
- one ticker per line, or
- comma-separated tickers
- lines starting with `#` are ignored

### Stage 1 tuning

You can relax or tighten the mechanical filter without editing code:

```bash
python screener.py --tickers FUTU,WULF --max-price 100 --min-implied-vol 60
```

## Workflow notes

- Stage 1 defaults to an implied volatility floor of **75%**.
- Stage 2 uses public news + price/liquidity checks to separate real businesses from garbage.
- Stage 3 is a rough DCF / margin-of-safety pass for names that survive the sieve.
- The report also shows sector spread so you can avoid clustering into one theme.

## Caveat

This is a screener, not a magic 8-ball. It helps you find diamonds faster. The market still does whatever it wants.
