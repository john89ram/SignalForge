# Stage 3 Alignment Review

## Scope
Reviewed the full `stages/stage3/` folder, including:
- root docs: `README.md`, `mission.md`, `verdict.md`
- runner spec and implementation: `code/README.md`, `code/run_stage3.py`
- output artifacts: `output/*.csv`
- audit artifacts: `audit_logs/*.md`, `audit_logs/*.log`, `audit_logs/*.jsonl`
- latest IONQ one-off artifacts created during the user-requested Stage 3 run

Verification command run:

```bash
PYTHONPATH=/home/hermes/market-funnel pytest -q tests/test_stage3_runner.py tests/test_screener.py -q
```

Result: `28 passed` for the targeted Stage 3 / screener tests.

## High-confidence alignment problems

### 1. Stage 3 currently has two competing contracts

The Stage 3 folder's canonical documents say Stage 3 is a thin runner around `screener.py`'s existing mechanical DCF engine:

- `mission.md`: Stage 3 uses a 5-year DCF model with Category A/B scenario weights.
- `code/README.md`: "The DCF engine already exists. Do not rewrite it."
- `audit_logs/stage3_handoff_review_20260525T193038Z.md`: Stage 3 should not rewrite valuation logic or tune thresholds.

But the current user-facing Stage 3 expectations saved in skills/memory require a fuller analyst methodology:

- Category B path: Cash Runway → Revenue Trajectory → Core Technology/Moat → Management → Scenarios.
- Company-specific, time-bound watch/kill signals.
- Deep-tech / quantum names should not rely solely on a punitive near-term FCF DCF.
- IONQ specifically has a validated Step 1–6 framework with a 256-qubit end-2027 commercial proof watch signal.

The one-off IONQ report in `audit_logs/IONQ_stage3_user_report_20260525T223405Z.md` acknowledges this by separating:

- pipeline mechanical output, and
- analyst overlay.

That separation is not encoded in the canonical Stage 3 mission/README/output contract, so the folder is internally split between "mechanical runner" and "full Stage 3 analyst report."

### 2. Stage 3 output is not carrying the required user-facing Stage 3 fields

`output/Stage3_Report.csv` currently contains valuation fields but not the full Stage 3 methodology fields the user expects:

- no cash runway fields,
- no annual vs quarterly burn warning,
- no revenue guidance/RPO fields,
- no moat/management verdict fields,
- no operational watch/kill notes except APLD,
- no scenario assumption transparency beyond raw projected rows inside the internal payload,
- no distinction between mechanical DCF result and analyst-overlay valuation.

The output therefore can satisfy the runner build contract while failing the user's Stage 3 analysis contract.

### 3. Generic watch signals violate the current reporting standard

Most non-APLD Stage 3 rows use generic watch signals:

- Category A: `Close below the 50-day SMA by 5% on elevated volume`
- Category B: `Next revenue step-down below 50% YoY or cash runway under 18 months`

This conflicts with the Stage 3 reporting standard that watch/kill signals should be company-specific and operationally anchored when possible.

IONQ is the clearest example:

- CSV watch signal: generic revenue/cash runway threshold.
- User-approved IONQ signal: customer-verified, independently reproducible result on a real commercial problem using the 256-qubit system by end-2027, with peer-reviewed third-party confirmation as upside validation.

### 4. IONQ exposed the model mismatch clearly

The live IONQ runner output:

- Stage 2 tier: `Standard`
- Stage 3 category: `B`
- mechanical weighted fair value: `1.1634734721853721`
- MOS threshold: `0.5817367360926861`
- watch signal: generic Category B threshold

The user-facing IONQ analysis needed:

- SEC source alignment,
- distorted GAAP net income explanation,
- total liquidity including short-term and long-term investments,
- FY burn denominator plus Q1 burn acceleration warning,
- revenue trajectory with guidance/RPO,
- quantum moat/management analysis,
- milestone-based watch/kill signal,
- scenario overlay that does not treat the FCF DCF as the only useful valuation lens.

This is the likely source of the user's "misaligned again" comment.

### 5. There are two Stage 2 artifact lineages that imply different tier meanings

Current canonical Stage 2 input used by Stage 3:

`/home/hermes/market-funnel/stages/stage2/output/Stage2_Report.csv`

- rows: 71
- tiers: Diamond 6, Strong 15, Standard 27, Watch 17, Eliminated 6
- IONQ: Standard, HP left 6 / 10

Legacy / exchange-run Stage 2 artifact:

`/home/hermes/market-funnel/exchange_enrichment_runs/nasdaq_summary_rough_scan_1b_10to75_vol1m_enrich/Stage2_Report.csv`

- rows: 71
- tiers: Diamond 27, Gold 42, Silver 2
- IONQ: Diamond, HP left 8 / 8

The Stage 3 folder is aligned to the newer Diamond/Strong/Standard/Watch/Eliminated contract, while persistent user preference/memory still includes HP tiers as Diamond/Gold/Silver/Bronze/Iron. This tier naming drift can create dashboard and interpretation confusion.

### 6. `verdict.md` says the output is GREEN even though acceptance criteria say all NO ENTRY / QC FAIL should trigger investigation

`mission.md` says:

> DIAMOND + ENTRY count is credible: if all processed names return NO ENTRY or QC FAIL, stop and investigate

The latest `verdict.md` says:

- verdict count: `{"NO ENTRY": 16, "QC FAIL": 5}`
- no actionable entries found
- valuation output: GREEN

That may be defensible after investigation, but the folder does not clearly separate:

- runner mechanics green,
- source/QC remediation green,
- analyst-methodology not yet aligned,
- actionable-output absent but accepted as a sieve result.

The current wording can read like the Stage 3 methodology is fully production-ready, when the IONQ test shows the methodology is not aligned with the user's expected analysis framework.

### 7. Untracked IONQ artifacts are now in Stage 3 audit/output folders

`git status --short` showed:

```text
?? stages/stage3/audit_logs/IONQ_stage3_full_payload_20260525T223405Z.json
?? stages/stage3/audit_logs/IONQ_stage3_user_report_20260525T223405Z.md
```

These were created during the one-off IONQ request and are useful evidence, but they are not part of the committed canonical Stage 3 contract. They also make the folder look like it supports an analyst overlay that the main Stage 3 runner does not actually produce.

## What is working

- `run_stage3.py` mechanics are largely aligned with the runner build brief:
  - consumes `stages/stage2/output/Stage2_Report.csv`,
  - applies tier cascade,
  - skips Eliminated / ineligible rows,
  - fetches fresh quote data,
  - loads SEC companyfacts,
  - reconstructs `TickerAnalysis`,
  - preserves Stage 2 kills/flags aliases,
  - emits CSV/log/JSONL artifacts,
  - isolates symbol failures into QC FAIL rows.

- Targeted tests pass:
  - runner cascade tests,
  - Stage 2 alias tests,
  - QC fail isolation tests,
  - screener Stage 3 source/QC hardening tests.

- APLD is the only clear example where Stage 3 has a ticker-specific valuation method plus operational watch/kill signal in the canonical output.

## Root cause hypothesis

The folder evolved in two different directions:

1. **Engineering runner contract:** build a safe, auditable batch wrapper around the existing `screener.py` DCF engine.
2. **User analysis contract:** produce full Stage 3 investment-quality reports with source-aligned fundamentals, company-specific operational signals, and scenario assumptions that match the company's business model.

The runner contract was implemented and tested. The analysis contract was only partially encoded in skills/memory and one-off reports. Because the Stage 3 folder still frames the mechanical DCF runner as the canonical Stage 3 output, it now overstates alignment.

## Recommended remediation, in order

### Step 1 — Decide and document the split

Update Stage 3 docs to explicitly define two layers:

1. **Stage 3 mechanical runner**
   - batch CSV screening,
   - fast valuation / QC gate,
   - conservative `ENTRY` / `NO ENTRY` labels,
   - useful for ranking and triage.

2. **Stage 3 full analyst report**
   - required before a user-facing final conclusion on a known/important name,
   - uses the full Category A/B methodology,
   - includes company-specific operational watch/kill signals,
   - may override or contextualize the mechanical FCF output when the business model requires a different lens.

### Step 2 — Rename or qualify the mechanical output

Avoid implying that `Stage3_Report.csv` is the full Stage 3 analysis. Consider documenting it as:

- `Stage3_Mechanical_Report.csv`, or
- "Stage 3 mechanical screen output" in the README/verdict.

### Step 3 — Add report-level fields or a separate analyst report artifact

For full Stage 3 names, create a separate output path such as:

`stages/stage3/output/reports/<SYMBOL>_Stage3_Analyst_Report.md`

Minimum fields:

- category and reason,
- Stage 2 anomaly notes,
- cash runway / burn acceleration,
- revenue trajectory / guidance / backlog or RPO,
- moat and management verdicts,
- scenario assumptions and weights,
- mechanical-runner output as a reference,
- analyst-overlay valuation if needed,
- company-specific watch signal,
- company-specific kill signal,
- final call.

### Step 4 — Patch generic watch signals

At minimum, mark generic watch signals as fallback placeholders in the CSV and do not present them as final Stage 3 watch signals for user-facing reports.

### Step 5 — Resolve tier naming drift

Pick the durable Stage 2 tier contract and update all Stage 3 docs accordingly. If Diamond/Strong/Standard/Watch is the canonical runner contract, explicitly say it is not the HP dashboard convention. If Diamond/Gold/Silver/Bronze/Iron is preferred for dashboarding, the Stage 3 runner/docs need to follow that instead.

### Step 6 — Clean up or commit the IONQ artifacts deliberately

Either:

- keep them as audit evidence and commit them with a note that they are one-off validation artifacts, or
- move them out of canonical Stage 3 folders so they do not imply unsupported runner functionality.

## Bottom line

The Stage 3 runner is mechanically healthy, but the Stage 3 folder is not aligned with the user's full Stage 3 methodology. The main gap is not test failure; it is contract drift.

The current folder says: "Stage 3 is the mechanical DCF runner."

The user expectation is: "Stage 3 is a full ownership-quality analysis with source alignment, business-model-aware valuation, and operational watch/kill signals."

Those need to be explicitly separated or unified before more ticker reports are trusted.
