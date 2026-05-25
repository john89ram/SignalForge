#!/usr/bin/env python3
"""Stage 2 report generator.

Consumes `Stage1_PASS.csv`, runs Stage 2 analysis, and writes a dedicated
`Stage2_Report.csv` with per-test outcomes plus HP remaining.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from screener import (
    BarchartSnapshot,
    HTTP,
    OptionsSnapshot,
    QuoteSnapshot,
    TickerAnalysis,
    analyze_ticker,
    summary_verdict,
)

DEFAULT_INPUT_NAME = "Stage1_PASS.csv"
DEFAULT_OUTPUT_NAME = "Stage2_Report.csv"

TEST_ORDER: List[Tuple[str, str]] = [
    ("headline catalyst", "headline_catalyst"),
    ("meme-stock signature", "meme_stock_signature"),
    ("event / operating floor", "event_operating_floor"),
    ("chart pattern", "chart_pattern"),
    ("news sentiment", "news_sentiment"),
    ("analyst consensus", "analyst_consensus"),
    ("liquidity sanity", "liquidity_sanity"),
    ("institutional ownership", "institutional_ownership"),
]


def _load_stage1_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _default_output_path(input_csv: str) -> str:
    return str(Path(input_csv).expanduser().with_name(DEFAULT_OUTPUT_NAME))


def _normalize_bool(value: object) -> str:
    text = str(value).strip().upper()
    return "PASS" if text in {"PASS", "TRUE", "1", "YES", "Y"} else "KILL"


def _stage1_text(row: dict) -> str:
    reasons = (row.get("stage1_reasons") or "").strip()
    if not reasons:
        return ""
    return reasons


def _stage2_test_map(analysis: TickerAnalysis) -> Dict[str, Dict[str, Any]]:
    return {str(test.get("name", "")): test for test in (analysis.stage2_tests or [])}


def _hp_tier(hp_total: int, hp_left: int) -> str:
    missing = max(0, int(hp_total) - int(hp_left))
    if missing == 0:
        return "Diamond"
    if missing <= 2:
        return "Gold"
    if missing == 3:
        return "Silver"
    if missing == 4:
        return "Bronze"
    return "Iron"


def _report_row(row: dict, analysis: TickerAnalysis) -> Dict[str, Any]:
    test_map = _stage2_test_map(analysis)
    kills = len(analysis.stage2_kills)
    stage2_verdict = "KILL" if kills >= 3 else ("WATCH PASS" if kills == 2 else "PASS")
    out: Dict[str, Any] = {
        "symbol": row.get("symbol", analysis.symbol),
        "name": row.get("name", ""),
        "master_exchange": row.get("master_exchange", ""),
        "sector": row.get("sector", analysis.quote.sector or ""),
        "industry": row.get("industry", analysis.quote.industry or ""),
        "price_proxy": row.get("price_proxy", row.get("previous_close", "")),
        "share_volume": row.get("share_volume", ""),
        "market_cap": row.get("market_cap", ""),
        "one_yr_target": row.get("one_yr_target", ""),
        "stage1_pass": _normalize_bool(row.get("stage1_pass", analysis.stage1_pass)),
        "stage1_reasons": _stage1_text(row),
        "stage2_verdict": stage2_verdict,
        "hp_tier": _hp_tier(analysis.stage2_hp_total, analysis.stage2_hp_left),
        "stage2_hard_kills": len(analysis.stage2_kills),
        "stage2_flags": len(analysis.stage2_flags),
        "stage2_hp_total": analysis.stage2_hp_total,
        "stage2_hp_left": analysis.stage2_hp_left,
        "stage2_score": analysis.stage2_score,
        "stage2_kills": " | ".join(analysis.stage2_kills),
        "stage2_flags_text": " | ".join(analysis.stage2_flags),
    }

    for test_name, slug in TEST_ORDER:
        test = test_map.get(test_name, {})
        out[f"{slug}_status"] = test.get("status", "")
        out[f"{slug}_score"] = test.get("score", "")
        out[f"{slug}_detail"] = test.get("detail", "")

    return out


def _analyze_row(row: dict, include_stage3: bool = True) -> TickerAnalysis:
    symbol = (row.get("symbol") or "").strip().upper()
    http = HTTP(retries=3)
    analysis = analyze_ticker(http, symbol, include_stage3=include_stage3)
    # Preserve the Stage 1 row metadata on the analysis object when the caller wants it.
    if row.get("stage1_pass") is not None:
        analysis.stage1_pass = _normalize_bool(row.get("stage1_pass")) == "PASS"
    if row.get("stage1_reasons"):
        analysis.stage1_reasons = [part.strip() for part in str(row.get("stage1_reasons", "")).split(" | ") if part.strip()]
    return analysis


def run(
    input_csv_path: str,
    *,
    output_csv_path: Optional[str] = None,
    workers: int = 2,
    include_stage3: bool = True,
    show_progress: bool = True,
) -> Dict[str, Any]:
    rows = _load_stage1_rows(input_csv_path)
    if output_csv_path is None:
        output_csv_path = _default_output_path(input_csv_path)

    output_path = Path(output_csv_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results: Dict[int, TickerAnalysis] = {}
    total = len(rows)

    if total == 0:
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("")
        return {
            "input_csv_path": input_csv_path,
            "output_csv_path": str(output_path),
            "input_rows": 0,
            "output_rows": 0,
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(_analyze_row, row, include_stage3): idx
            for idx, row in enumerate(rows)
        }
        completed = 0
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                analysis = future.result()
            except Exception as exc:  # noqa: BLE001
                symbol = (rows[idx].get("symbol") or "").strip().upper()
                analysis = TickerAnalysis(
                    symbol=symbol,
                    quote=QuoteSnapshot(symbol=symbol),
                    barchart=BarchartSnapshot(),
                    options=OptionsSnapshot(),
                    stage1_pass=False,
                    stage1_reasons=[f"stage2 analysis failed: {exc}"],
                )
            results[idx] = analysis
            completed += 1
            if show_progress:
                pct = (completed / total) * 100.0
                print(
                    f"[{completed:>3}/{total}] {analysis.symbol} verdict={summary_verdict(analysis)} "
                    f"hp_left={analysis.stage2_hp_left} score={analysis.stage2_score:.2f} ({pct:.1f}%)",
                    flush=True,
                )

    fieldnames: List[str] = [
        "symbol",
        "name",
        "master_exchange",
        "sector",
        "industry",
        "price_proxy",
        "share_volume",
        "market_cap",
        "one_yr_target",
        "stage1_pass",
        "stage1_reasons",
        "stage2_verdict",
        "hp_tier",
        "stage2_hard_kills",
        "stage2_flags",
        "stage2_hp_total",
        "stage2_hp_left",
        "stage2_score",
        "stage2_kills",
        "stage2_flags_text",
    ]
    for _, slug in TEST_ORDER:
        fieldnames.extend([f"{slug}_status", f"{slug}_score", f"{slug}_detail"])

    rows_out = [_report_row(rows[idx], results[idx]) for idx in range(total)]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)

    return {
        "input_csv_path": input_csv_path,
        "output_csv_path": str(output_path),
        "input_rows": total,
        "output_rows": len(rows_out),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 2 on Stage1_PASS and write Stage2_Report.csv")
    parser.add_argument("input_csv", nargs="?", help="Path to Stage1_PASS.csv")
    parser.add_argument("--output-csv", help=f"Where to write the report (default: {DEFAULT_OUTPUT_NAME} next to the input)")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent workers for Stage 2 analysis")
    parser.add_argument("--no-stage3", action="store_true", help="Skip Stage 3 within the analysis run")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress logging")
    args = parser.parse_args(argv)

    input_csv = args.input_csv or DEFAULT_INPUT_NAME
    result = run(
        input_csv,
        output_csv_path=args.output_csv,
        workers=args.workers,
        include_stage3=not args.no_stage3,
        show_progress=not args.quiet,
    )

    if not args.quiet:
        print("Stage 2 report complete")
        print(f"- Input CSV: {result['input_csv_path']}")
        print(f"- Output CSV: {result['output_csv_path']}")
        print(f"- Rows: {result['input_rows']} -> {result['output_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
