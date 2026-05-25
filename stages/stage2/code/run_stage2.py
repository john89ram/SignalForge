"""Canonical Stage 2 runner.

Consumes `stages/stage2/input/Stage1_PASS.csv`, runs the seven-test HP sieve,
writes `stages/stage2/output/Stage2_Report.csv`, and records audit logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from screener import BarchartSnapshot, HTTP, OptionsSnapshot, QuoteSnapshot, TickerAnalysis, analyze_stage2, analyze_ticker

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "stages" / "stage2" / "input" / "Stage1_PASS.csv"
DEFAULT_OUTPUT = REPO_ROOT / "stages" / "stage2" / "output" / "Stage2_Report.csv"
DEFAULT_LOG_DIR = REPO_ROOT / "stages" / "stage2" / "audit_logs"
TEST_ORDER: List[Tuple[str, str]] = [
    ("iv spike diagnosis", "iv_spike_diagnosis"),
    ("meme stock", "meme_stock"),
    ("chart pattern", "chart_pattern"),
    ("news sentiment", "news_sentiment"),
    ("analyst consensus", "analyst_consensus"),
    ("liquidity", "liquidity"),
    ("institutional ownership", "institutional_ownership"),
]


@dataclass(frozen=True)
class Stage2RunResult:
    input_csv_path: str
    output_csv_path: str
    log_path: str
    audit_jsonl_path: str
    input_rows: int
    output_rows: int
    tier_counts: Dict[str, int]
    verdict_counts: Dict[str, int]
    elapsed_seconds: float


def _load_stage1_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _normalize_bool(value: object) -> str:
    text = str(value).strip().upper()
    return "PASS" if text in {"PASS", "TRUE", "1", "YES", "Y"} else "KILL"


def _float(row: dict, *names: str) -> Optional[float]:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", ""))
            except ValueError:
                continue
    return None


def _int(row: dict, *names: str) -> Optional[int]:
    value = _float(row, *names)
    return int(value) if value is not None else None


def _test_map(analysis: TickerAnalysis) -> Dict[str, Dict[str, Any]]:
    return {str(test.get("name", "")): test for test in analysis.stage2_tests}


def _row_stage1_pass(row: dict, analysis: TickerAnalysis) -> str:
    return _normalize_bool(row.get("stage1_pass", row.get("stage1_step4_verdict", analysis.stage1_pass)))


def _row_stage1_reasons(row: dict) -> str:
    return row.get("stage1_reasons", row.get("stage1_step4_fail_reason", row.get("legacy_stage1_reasons", "")))


def _report_row(row: dict, analysis: TickerAnalysis) -> Dict[str, Any]:
    tests = _test_map(analysis)
    out: Dict[str, Any] = {
        "symbol": row.get("symbol", analysis.symbol),
        "name": row.get("name", ""),
        "master_exchange": row.get("master_exchange", ""),
        "sector": row.get("sector", analysis.quote.sector or ""),
        "industry": row.get("industry", analysis.quote.industry or ""),
        "price_proxy": row.get("price_proxy", row.get("previous_close", analysis.quote.price or "")),
        "share_volume": row.get("share_volume", analysis.quote.volume or ""),
        "market_cap": row.get("market_cap", analysis.quote.market_cap or ""),
        "one_yr_target": row.get("one_yr_target", analysis.quote.target_price or ""),
        "stage1_pass": _row_stage1_pass(row, analysis),
        "stage1_reasons": _row_stage1_reasons(row),
        "stage2_verdict": analysis.stage2_verdict,
        "eligible_for_stage3": str(bool(analysis.eligible_for_stage3)).upper(),
        "hp_tier": analysis.stage2_tier,
        "stage2_hp_total": analysis.stage2_hp_total,
        "stage2_hp_left": analysis.stage2_hp_left,
        "stage2_damage": analysis.stage2_hp_total - analysis.stage2_hp_left,
        "stage2_score": analysis.stage2_score,
        "stage2_bad_count": len(analysis.stage2_kills),
        "stage2_weak_count": len(analysis.stage2_flags),
        "stage2_bad_text": " | ".join(analysis.stage2_kills),
        "stage2_weak_text": " | ".join(analysis.stage2_flags),
    }
    for test_name, slug in TEST_ORDER:
        test = tests.get(test_name, {})
        out[f"{slug}_status"] = test.get("status", "")
        out[f"{slug}_hp_loss"] = test.get("hp_loss", "")
        out[f"{slug}_detail"] = test.get("detail", "")
    return out


def _fieldnames() -> List[str]:
    fields = [
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
        "eligible_for_stage3",
        "hp_tier",
        "stage2_hp_total",
        "stage2_hp_left",
        "stage2_damage",
        "stage2_score",
        "stage2_bad_count",
        "stage2_weak_count",
        "stage2_bad_text",
        "stage2_weak_text",
    ]
    for _, slug in TEST_ORDER:
        fields.extend([f"{slug}_status", f"{slug}_hp_loss", f"{slug}_detail"])
    return fields


def _analysis_from_input_row(row: dict) -> TickerAnalysis:
    symbol = (row.get("symbol") or "").strip().upper()
    analysis = TickerAnalysis(
        symbol=symbol,
        quote=QuoteSnapshot(
            symbol=symbol,
            price=_float(row, "price_proxy", "previous_close"),
            sector=row.get("sector") or None,
            industry=row.get("industry") or None,
            market_cap=_float(row, "market_cap"),
            volume=_float(row, "share_volume"),
            target_price=_float(row, "one_yr_target"),
        ),
        barchart=BarchartSnapshot(
            implied_volatility=_float(row, "barchart_implied_volatility", "stage1_step4_implied_volatility"),
            historical_volatility=_float(row, "barchart_historical_volatility"),
            iv_percentile=_float(row, "barchart_iv_percentile"),
            iv_rank=_float(row, "barchart_iv_rank"),
            iv_high=_float(row, "barchart_iv_high"),
            iv_low=_float(row, "barchart_iv_low"),
            expected_move=_float(row, "barchart_expected_move"),
        ),
        options=OptionsSnapshot(
            total_volume=_int(row, "options_volume"),
            total_open_interest=_int(row, "open_interest"),
            atm_bid_ask_spread=_float(row, "atm_bid_ask_spread"),
        ),
    )
    analysis.stage1_pass = _row_stage1_pass(row, analysis) == "PASS"
    reasons = _row_stage1_reasons(row)
    if reasons:
        analysis.stage1_reasons = [part.strip() for part in str(reasons).split(" | ") if part.strip()]
    analyze_stage2(analysis, price_history=None)
    return analysis


def _analyze_row(row: dict, include_stage3: bool, offline_input_only: bool = False) -> TickerAnalysis:
    if offline_input_only:
        return _analysis_from_input_row(row)
    symbol = (row.get("symbol") or "").strip().upper()
    http = HTTP(timeout=10, retries=1)
    analysis = analyze_ticker(
        http,
        symbol,
        include_stage3=include_stage3,
        min_implied_vol=0,
        min_options_volume=0,
        min_market_cap=0,
        min_today_volume=0,
        min_open_interest=0,
        min_price=0,
        max_price=float("inf"),
    )
    if row.get("stage1_pass") is not None or row.get("stage1_step4_verdict") is not None:
        analysis.stage1_pass = _row_stage1_pass(row, analysis) == "PASS"
    reasons = _row_stage1_reasons(row)
    if reasons:
        analysis.stage1_reasons = [part.strip() for part in str(reasons).split(" | ") if part.strip()]
    return analysis


def _failed_analysis(row: dict, exc: Exception) -> TickerAnalysis:
    symbol = (row.get("symbol") or "").strip().upper()
    analysis = TickerAnalysis(
        symbol=symbol,
        quote=QuoteSnapshot(symbol=symbol),
        barchart=BarchartSnapshot(),
        options=OptionsSnapshot(),
        stage1_pass=_normalize_bool(row.get("stage1_pass", "PASS")) == "PASS",
    )
    analysis.stage2_verdict = "ERROR"
    analysis.stage2_tier = "Eliminated"
    analysis.eligible_for_stage3 = False
    analysis.stage2_hp_total = 10
    analysis.stage2_hp_left = 0
    analysis.stage2_kills = [f"stage2 analysis failed: {exc}"]
    return analysis


def run(
    input_csv_path: Path | str = DEFAULT_INPUT,
    *,
    output_csv_path: Path | str = DEFAULT_OUTPUT,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    workers: int = 2,
    include_stage3: bool = False,
    offline_input_only: bool = False,
    show_progress: bool = True,
) -> Stage2RunResult:
    start = time.perf_counter()
    input_path = Path(input_csv_path).expanduser().resolve()
    output_path = Path(output_csv_path).expanduser().resolve()
    log_root = Path(log_dir).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_root / f"stage2_run_{timestamp}.log"
    audit_path = log_root / f"stage2_run_{timestamp}.jsonl"

    rows = _load_stage1_rows(input_path)
    total = len(rows)
    results: Dict[int, TickerAnalysis] = {}
    log_lines = [f"Stage 2 run started {timestamp}", f"input={input_path}", f"output={output_path}", f"rows={total}"]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(_analyze_row, row, include_stage3, offline_input_only): idx for idx, row in enumerate(rows)}
        completed = 0
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                analysis = future.result()
            except Exception as exc:  # noqa: BLE001
                analysis = _failed_analysis(rows[idx], exc)
            results[idx] = analysis
            completed += 1
            line = (
                f"[{completed:>3}/{total}] {analysis.symbol} tier={analysis.stage2_tier or 'UNKNOWN'} "
                f"verdict={analysis.stage2_verdict or 'UNKNOWN'} hp_left={analysis.stage2_hp_left} "
                f"damage={analysis.stage2_hp_total - analysis.stage2_hp_left}"
            )
            log_lines.append(line)
            if show_progress:
                print(line, flush=True)

    rows_out = [_report_row(rows[idx], results[idx]) for idx in range(total)]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_fieldnames())
        writer.writeheader()
        writer.writerows(rows_out)

    tier_counts = Counter(row["hp_tier"] for row in rows_out)
    verdict_counts = Counter(row["stage2_verdict"] for row in rows_out)
    elapsed = round(time.perf_counter() - start, 3)

    summary = {
        "event": "stage2_run_complete",
        "timestamp_utc": timestamp,
        "input_csv_path": str(input_path),
        "output_csv_path": str(output_path),
        "input_rows": total,
        "output_rows": len(rows_out),
        "tier_counts": dict(tier_counts),
        "verdict_counts": dict(verdict_counts),
        "elapsed_seconds": elapsed,
    }
    log_lines.append("summary=" + json.dumps(summary, sort_keys=True))
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, sort_keys=True) + "\n")

    if show_progress:
        print("Stage 2 report complete")
        print(f"- Output CSV: {output_path}")
        print(f"- Log: {log_path}")
        print(f"- Audit JSONL: {audit_path}")
        print(f"- Tier counts: {dict(tier_counts)}")

    return Stage2RunResult(
        input_csv_path=str(input_path),
        output_csv_path=str(output_path),
        log_path=str(log_path),
        audit_jsonl_path=str(audit_path),
        input_rows=total,
        output_rows=len(rows_out),
        tier_counts=dict(tier_counts),
        verdict_counts=dict(verdict_counts),
        elapsed_seconds=elapsed,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run canonical Stage 2 seven-test HP sieve")
    parser.add_argument("input_csv", nargs="?", default=str(DEFAULT_INPUT), help="Path to Stage1_PASS.csv")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT), help="Where to write Stage2_Report.csv")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Directory for Stage 2 audit logs")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent workers")
    parser.add_argument("--include-stage3", action="store_true", help="Also run Stage 3 for eligible names during analysis")
    parser.add_argument("--offline-input-only", action="store_true", help="Build the report from Stage1_PASS fields only; unavailable live-data fields become SKIP/PASS defaults")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args(argv)
    run(
        args.input_csv,
        output_csv_path=args.output_csv,
        log_dir=args.log_dir,
        workers=args.workers,
        include_stage3=args.include_stage3,
        offline_input_only=args.offline_input_only,
        show_progress=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
