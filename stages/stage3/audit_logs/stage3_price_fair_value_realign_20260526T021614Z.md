# Stage 3 price / fair-value realignment — 2026-05-26T02:16:14Z

## Why this review happened
The user flagged that IONQ, MARA, and other Diamond-rated names had implausibly low Stage 3 weighted fair values compared with familiar trading history and the Stage 2 `one_yr_target` values. The user also noted that Stage 2 report artifacts include normal analyst target values that should have made the mismatch obvious.

## Files and inputs reviewed

Canonical Stage 2 input used by Stage 3:

```text
stages/stage2/output/Stage2_Report.csv
```

Additional Stage 2 lineage artifacts found:

```text
runs/full_review_current_universe/market_collection/exchange_enrichment/Stage2_Report.csv
exchange_enrichment_runs/nasdaq_summary_rough_scan_1b_10to75_vol1m_enrich/Stage2_Report.csv
```

Current Stage 3 output regenerated after fixes:

```text
stages/stage3/output/Stage3_Report.csv
stages/stage3/audit_logs/stage3_run_20260526T021614Z.log
stages/stage3/audit_logs/stage3_run_20260526T021614Z.jsonl
```

## Confirmed Stage 2 reference values

### MARA
Canonical Stage 2 row:

```text
price_proxy: 13.55
one_yr_target: 15.5
market_cap: 5.265B
hp_tier: Diamond
stage2_hp_left: 10
stage2_score: 7.0
```

Current Finviz quote during review:

```text
price: 13.81
Finviz target: 17.78
market_cap: 5.27B
```

### IONQ
Canonical Stage 2 row:

```text
price_proxy: 58.89
one_yr_target: 65.0
market_cap: 23.755B
hp_tier: Standard
stage2_hp_left: 6
stage2_score: 5.0
```

Older enrichment lineage row:

```text
hp_tier: Diamond
stage2_hp_left: 8 / 8
one_yr_target: 65.0
```

Current Finviz quote during review:

```text
price: 63.64
Finviz target: 69.95
market_cap: 23.75B
```

### HIMS
HIMS was not present in the current Stage 2 report artifacts reviewed, but direct Stage 3 source validation was run because the user specifically cited it.

Current Finviz quote during review:

```text
price: 23.75
Finviz target: 27.91
market_cap: 5.41B
```

## Bugs / model defects found

### 1. Revenue tag selection understated MARA revenue

Before this fix, `load_sec_companyfacts()` used the first annual revenue tag that appeared in a fixed priority list. For MARA, this selected:

```text
RevenueFromContractWithCustomerExcludingAssessedTax FY2025 = 58.704M
```

But MARA also reports broader total revenue:

```text
Revenues FY2025 = 907.093M
Revenues FY2024 = 656.378M
```

The narrow tag appears to capture a subset of revenue and should not drive total-company valuation.

Fix implemented:

- collect annual rows for all known revenue tags,
- choose the tag with the most recent annual date,
- if several tags share that latest date, choose the largest value as the best total-revenue proxy.

This preserves IONQ on its proper current contract-revenue tag while preventing MARA from being valued off an understated fee-style tag.

### 2. Flow facts mixed latest quarter with annual revenue

Before this fix, operating income / operating cash flow / net income used the latest row after sorting, which could be a recent quarter, while revenue used annual rows. That mixed quarterly flow facts with annual revenue.

Examples observed:

- MARA revenue used FY2025 but OCF was Q1 2026.
- IONQ revenue used FY2025 but OCF was Q1 2026.
- HIMS revenue used FY2025 but net income/op income were Q1 2026.

Fix implemented:

- prefer annual rows for `NetIncomeLoss`, `OperatingIncomeLoss`, and `NetCashProvidedByUsedInOperatingActivities`,
- keep point-in-time latest rows for cash and shares.

### 3. Share sanity check was incorrectly QC-failing legitimate valuation gaps

The previous post-DCF check compared:

```text
weighted_fair_value * shares
```

against current market cap and QC-failed when the valuation-implied equity value was more than 20% above market cap.

That is not a share denominator sanity check; it is often just an undervaluation signal. Stage 3 should not QC-fail a stock simply because the model says fair value is above current market cap.

Fix implemented:

- moved the responsibility back to `stage3_share_count()`, which compares SEC shares directly with market-cap-implied shares before valuation,
- removed post-valuation market-cap-difference QC failure from both the generic Stage 3 model and APLD custom model.

This directly fixed HIMS producing `QC FAIL` instead of a real fair value.

## Tests added / updated

Added or updated tests for:

- choosing the broadest latest annual revenue tag when multiple revenue tags exist for the same year,
- preferring annual flow facts over latest quarterly rows,
- allowing high fair-value-vs-market-cap valuation signals instead of QC-failing them,
- preserving the existing low-DCF-overvaluation behavior.

Verification command:

```bash
PYTHONPATH=/home/hermes/market-funnel pytest -q tests/test_screener.py tests/test_stage3_runner.py
```

Result:

```text
30 passed, 3 subtests passed
```

## Regenerated Stage 3 output after code fixes

Command:

```bash
python -u -m stages.stage3.code.run_stage3 \
  stages/stage2/output/Stage2_Report.csv \
  --output-csv stages/stage3/output/Stage3_Report.csv \
  --workers 2 \
  --min-verdicts 5 \
  --tiers Diamond,Strong
```

Result summary:

```text
Verdict counts: {'NO ENTRY': 17, 'DIAMOND': 1, 'QC FAIL': 2, 'ENTRY': 1}
```

New actionable names surfaced:

```text
CLSK  DIAMOND  Category A  FV 21.10  MOS 16.88  Price 15.97
PATH  ENTRY    Category A  FV 14.00  MOS 11.20  Price 10.93
```

## Selected post-fix values

### MARA

```text
Price: 13.81
Finviz target: 17.78
Stage 2 one_yr_target: 15.50
Stage 3 category: B
Revenue used after fix: 907.093M
Previous revenue used after fix: 656.378M
OCF used after fix: -802.725M FY2025
Shares: 380.873M
Weighted FV: 0.26
MOS threshold: 0.13
Verdict: NO ENTRY
```

Interpretation:

The data-source bug is fixed, but the generic FCF DCF still gives MARA an extremely low value because FY2025 operating cash flow is deeply negative and the generic Category B model does not include BTC / digital-asset NAV or crypto-cycle sensitivity. For MARA, a proper Stage 3 fair weighted value should likely use a crypto-miner/NAV-aware model rather than the generic DCF alone.

### IONQ

```text
Price: 63.64
Finviz target: 69.95
Stage 2 one_yr_target: 65.00
Stage 3 category: B
Revenue used: 130.016M FY2025
OCF used after fix: -283.187M FY2025
Shares: 373.171M
Mechanical weighted FV: 1.16
Mechanical MOS threshold: 0.58
Verdict: NO ENTRY
```

Interpretation:

The source-alignment fixes are correct, but IONQ remains a poor fit for a generic near-term FCF DCF. The mechanical model treats IONQ as a pre-profit cash-burning company and gives almost no credit for the long-duration quantum option value, RPO/backlog trajectory, net investments/liquidity beyond cash, or technology milestone probability. The earlier analyst overlay value near the mid-$30s is closer to the intended full Stage 3 approach than the mechanical $1.16 output.

### HIMS

```text
Price: 23.75
Finviz target: 27.91
Stage 3 category: A
Revenue used: 2.348B FY2025
OCF used after fix: 300.006M FY2025
Shares: market-cap-implied, because SEC common-share tag was unusable
Weighted FV: 58.04
MOS threshold: 46.43
Verdict if Stage 1/2 pass and <= MOS: valuation-supported
```

Interpretation:

HIMS was the clearest proof that the post-valuation share sanity guard was wrong. After removal, Stage 3 produces a normal fair value rather than QC FAIL. However, HIMS still needs the user-specific Stage 3 paradox/patent-risk tests before final user-facing approval.

## Remaining misalignment after code fixes

The source bugs are partially fixed, but full realignment is not complete.

The generic Stage 3 model is still unsuitable as the sole fair-value engine for several user-known stocks:

- **MARA / RIOT / CLSK / WULF / IREN:** need crypto-miner / BTC-NAV-aware valuation, not generic FCF only.
- **IONQ / RGTI / QBTS / QUBT:** need deep-tech milestone and liquidity-adjusted scenario valuation, not generic 5-year FCF only.
- **HIMS:** needs Category A plus the HIMS-specific paradox / Novo patent-risk overlay.
- **APLD:** already has a bespoke infrastructure buildout model and is the best current example of correct special handling.

## Recommended next engineering step

Do not trust `Stage3_Report.csv` as a final user-facing fair-value source yet.

Next, Stage 3 needs a model-family router:

```text
generic_category_a_dcf
generic_category_b_dcf
crypto_miner_nav_cycle_model
deep_tech_milestone_model
construction_phase_infra_model  # APLD already lives here
hims_category_a_paradox_overlay
```

Each output row should include:

```text
valuation_model
mechanical_fv
analyst_or_model_family_fv
mos_threshold
current_price
one_yr_target
target_vs_model_delta_pct
source_alignment_notes
```

This will make a mismatch like IONQ $1.16 vs target $69.95 impossible to miss.

## Bottom line

The user is correct: a proper Stage 3 fair weighted value should not blindly output sub-$2 fair values for familiar names without flagging model mismatch.

Completed fixes:

- MARA revenue source is no longer understated by the narrow revenue tag.
- Annual flow facts are aligned with annual revenue.
- HIMS no longer QC-fails just because fair value is above market cap.
- Tests pass.
- Stage 3 output was regenerated.

Still required:

- add valuation-model families for crypto miners and deep-tech names,
- carry Stage 2 `one_yr_target` into Stage 3 output as a sanity benchmark,
- flag major target-vs-model divergences,
- keep generic FCF DCF as a baseline, not the final answer for all business models.
