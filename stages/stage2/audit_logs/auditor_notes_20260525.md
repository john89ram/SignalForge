# Auditor Notes — Stage 2 Live Run Preparation

**Date:** 2026-05-25
**Auditor:** Hermes Gatekeeper
**For:** Hermes (pre-live-run briefing)

---

## Status Recap

All five blocking audit items (CRIT-1, HIGH-1 through HIGH-4) have been reviewed and confirmed fixed. The code is correct. The patch is clean. The two remaining LOW items do not affect run correctness and are not blockers.

Stage 2 is cleared for a **live validation run**. It is not cleared for production trading decisions until that live run completes and produces a credible result.

---

## Before You Run — Operational Warning

The live Stage 2 runner (`run_stage2.py`) has no inter-symbol delay on the live fetch path. `_analyze_row` calls `analyze_ticker`, which makes four outbound HTTP calls per symbol:

1. Finviz quote page
2. Barchart overview
3. Finviz options page
4. Nasdaq metadata

At 71 symbols that is approximately 284 HTTP calls. The `ThreadPoolExecutor` fires these concurrently based on the `--workers` setting. Unlike Stage 1 steps (which have an explicit `--delay-seconds` guard), Stage 2 has no throttle between symbols on the live path.

**Recommended run command:**

```bash
python -m stages.stage2.code.run_stage2 \
  stages/stage2/input/Stage1_PASS.csv \
  --output-csv stages/stage2/output/Stage2_Report.csv \
  --workers 2
```

Keep workers at **2**, not 4. It will be slower but it avoids mid-run rate blocks from Finviz or Barchart. A partial result with a corrupted audit log is worse than a slow clean run.

If you get rate-blocked partway through, the run will produce an incomplete output CSV with `ERROR` verdicts on the blocked symbols. Do not use that output for anything. Wait, then re-run from scratch.

---

## What a Healthy Live Run Looks Like

The offline run produced **71/71 PASS, 0 Watch, 0 Eliminated** because 5 of 7 tests had no live data to work with. A live run should look meaningfully different.

**Signals that the run is working correctly:**

- At least some `Watch` or `Eliminated` tier names appear. If you see 71/71 PASS again on a live run, stop — something is not fetching correctly, likely news or institutional ownership.
- `InstitutionalOwnershipTest` produces a mix of PASS, WEAK, BAD, and SKIP results rather than all-SKIP. If it is still all-SKIP, `inst_own` is not being populated from Finviz — check `parse_finviz_quote` and confirm the `Inst Own` label is being parsed from the HTML.
- `ChartPatternTest` produces some non-PASS results. With the SMA fix in place, any stock below its 200-day or 50-day moving average should now register correctly. If everything comes back PASS on chart pattern, check that `sma50` and `sma200` are non-None on the `QuoteSnapshot` objects after the Finviz fetch.
- `IVSpikeDiagnosisTest` and `NewsSentimentTest` produce some WEAK results from headline keywords. A universe of 71 high-IV names should have at least a few analyst downgrades, misses, or negative flows in recent news.

**Tier distribution to expect (rough):**

The offline run had Diamond=21, Strong=38, Standard=12. Once live data populates news, SMA, and institutional ownership, expect the Diamond count to compress and Standard/Watch to grow. A live Diamond count above ~15 would be worth scrutinizing — verify those names individually before treating them as top-tier.

---

## Remaining Low-Priority Items (post-live-run follow-ups)

These are not blockers but should be addressed in a follow-up pass:

**LOW-1 — Defensive Finviz volume parsing**
`parse_finviz_quote` sets `quote.volume` to `Rel Volume` (a float like 1.2) if the `Volume` label is absent from the Finviz HTML. If Finviz ever drops the `Volume` key due to a layout change, all stocks silently fail the 1M-share Stage 1 volume filter — no error, universal quiet failure. Add a fallback guard and a log warning on that code path.

**LOW-2 — `stage2_score` conflates "tested and good" with "untestable"**
`SKIP` produces `score = 0.0`, identical to a failed test. If `stage2_score` is later used directly for Stage 3 prioritization ranking, a stock that earned a clean score and a stock that was simply missing data will look equivalent. Consider adding `stage2_tested_count` and `stage2_skipped_count` columns to the output CSV so downstream consumers can weight scores by coverage. Not urgent until Stage 3 ranking logic is built.

---

## One Thing to Watch in the Live Output

Check the `stage2_score` distribution after the live run. In offline mode every name scores between 0 and ~6 (since 5 tests contribute nothing). In live mode the scores should spread across the full 0–7 range. If you see scores clustering unnaturally at the top, cross-check against the individual test status columns to confirm all seven tests are actually firing.

---

## Final Note

The audit patch was clean and the responses were accurate. Hermes addressed every blocker correctly and added the right regression tests. The codebase is in good shape for a live run. The one remaining open question is purely operational — does the live data fetch work end-to-end against real Finviz and Barchart responses at the 71-symbol scale. That is what this run is for.

Run it, check the audit log, and compare the tier distribution to the offline baseline. If the run is clean and the results are credible, Stage 2 is production-cleared.
