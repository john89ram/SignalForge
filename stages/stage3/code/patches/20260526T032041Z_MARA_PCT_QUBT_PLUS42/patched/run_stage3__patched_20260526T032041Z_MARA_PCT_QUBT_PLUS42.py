"""Canonical Stage 3 runner.

Consumes `stages/stage2/output/Stage2_Report.csv`, runs the existing Stage 3
valuation engine, writes `stages/stage3/output/Stage3_Report.csv`, and records
human-readable plus JSONL audit logs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from screener import (  # noqa: E402
    BarchartSnapshot,
    HTTP,
    OptionsSnapshot,
    QuoteSnapshot,
    SECFacts,
    TickerAnalysis,
    load_sec_companyfacts,
    parse_finviz_quote,
    stage3_analysis,
    summary_verdict,
)

DEFAULT_INPUT = REPO_ROOT / "stages" / "stage2" / "output" / "Stage2_Report.csv"
DEFAULT_OUTPUT = REPO_ROOT / "stages" / "stage3" / "output" / "Stage3_Report.csv"
DEFAULT_LOG_DIR = REPO_ROOT / "stages" / "stage3" / "audit_logs"
DEFAULT_TIERS = ["Diamond", "Strong", "Standard", "Watch"]
TIER_ORDER = {"Diamond": 0, "Strong": 1, "Standard": 2, "Watch": 3, "Eliminated": 4, "": 5}
ACTIONABLE_VERDICTS = {"DIAMOND", "ENTRY"}
FAIR_VALUE_TARGET_MISALIGNMENT_PCT = 50.0


@dataclass(frozen=True)
class Stage3RunResult:
    input_csv_path: str
    output_csv_path: str
    log_path: str
    audit_jsonl_path: str
    input_rows: int
    eligible_rows: int
    symbols_processed: int
    tiers_consumed: List[str]
    cascade_stopped_early: bool
    verdict_counts: Dict[str, int]
    actionable_count: int
    elapsed_seconds: float


def _load_stage2_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _get_tier(row: dict) -> str:
    """Resolve tier from actual or aliased Stage 2 column names."""
    return (row.get("stage2_tier") or row.get("hp_tier") or "").strip()


def _get_kills_text(row: dict) -> str:
    """Resolve BAD verdict text from actual or aliased Stage 2 column names."""
    return row.get("stage2_kills") or row.get("stage2_bad_text") or ""


def _get_flags_text(row: dict) -> str:
    """Resolve WEAK verdict text from actual or aliased Stage 2 column names."""
    return row.get("stage2_flags") or row.get("stage2_weak_text") or ""


def _is_stage3_eligible(row: dict) -> bool:
    tier = _get_tier(row)
    eligible_text = str(row.get("eligible_for_stage3", "TRUE")).strip().upper()
    eligible = eligible_text not in {"FALSE", "0", "NO", "N", "KILL", "ELIMINATED"}
    return tier != "Eliminated" and eligible


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


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _fmt_price(value: Optional[float]) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def _classify_target_misalignment(
    *,
    severe: bool,
    weighted_fair_value: Optional[float],
    current_price: Optional[float],
    benchmark_value: Optional[float],
    stage3_category: Optional[str],
    stage3_verdict: Optional[str],
    sector: Optional[str],
    share_count_source: Optional[str],
    share_qc_detail: Optional[str],
) -> str:
    """Classify target/FV gaps without assuming every gap is a patchable bug.

    A severe gap against Stage 2/Finviz targets is evidence for review, not
    proof that automated code should force valuations toward those targets.
    This classifier keeps `software_patch_required` reserved for confirmed
    source/denominator defects while preserving the severe alignment warning.
    """
    if not severe:
        return "NO_PATCH_SAFE"
    if share_qc_detail:
        return "SHARE_DENOMINATOR_BUG"
    if share_count_source == "market_cap_implied":
        return "DATA_PROVIDER_ISSUE"
    if current_price and benchmark_value and current_price > 0:
        target_vs_price = abs((benchmark_value - current_price) / current_price) * 100.0
        if target_vs_price > FAIR_VALUE_TARGET_MISALIGNMENT_PCT:
            return "TARGET_OUTLIER"
    sector_norm = (sector or "").strip().lower()
    model_sensitive_sectors = {
        "basic materials",
        "consumer discretionary",
        "energy",
        "finance",
        "health care",
        "industrials",
        "miscellaneous",
        "utilities",
    }
    if stage3_category == "B" or sector_norm in model_sensitive_sectors:
        return "MODEL_FAMILY_MISSING"
    # For mature/profitable Technology names, a target gap alone is not enough
    # to prove a software patch. Keep the warning, but do not auto-escalate.
    return "NO_PATCH_SAFE"


def _target_alignment(
    weighted_fair_value: Optional[float],
    stage2_target: Optional[float],
    finviz_target: Optional[float],
    *,
    current_price: Optional[float] = None,
    stage3_category: Optional[str] = None,
    stage3_verdict: Optional[str] = None,
    sector: Optional[str] = None,
    share_count_source: Optional[str] = None,
    share_qc_detail: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare Stage 3 fair value to external target benchmarks.

    The guard intentionally uses the closest available benchmark so a stale or
    outlier target source does not create a false software-patch requirement.
    Severe gaps remain visible, but automated patch escalation is reserved for
    classifications that are actually patchable in code.
    """
    targets = [
        ("Stage 2 target", stage2_target),
        ("Finviz target", finviz_target),
    ]
    usable_targets = [(label, value) for label, value in targets if value is not None and value > 0]
    if weighted_fair_value is None or not usable_targets:
        return {
            "target_benchmark_price": "",
            "fair_value_target_gap_pct": "",
            "fair_value_target_alignment": "NO_TARGET_CHECK",
            "software_patch_required": "FALSE",
            "fair_value_target_gap_detail": "target check skipped: missing Stage 3 FV or positive target benchmark",
        }

    comparisons = [
        (label, value, ((weighted_fair_value - value) / value) * 100.0)
        for label, value in usable_targets
    ]
    benchmark_label, benchmark_value, gap_pct = min(comparisons, key=lambda item: abs(item[2]))
    severe = abs(gap_pct) > FAIR_VALUE_TARGET_MISALIGNMENT_PCT
    direction = "above" if gap_pct > 0 else "below"
    target_detail = "; ".join(f"{label} {_fmt_price(value)}" for label, value in usable_targets)
    detail = (
        f"Stage 3 FV {_fmt_price(weighted_fair_value)} is {gap_pct:.1f}% {direction} "
        f"closest benchmark {benchmark_label} {_fmt_price(benchmark_value)}; {target_detail}"
    )
    classification = _classify_target_misalignment(
        severe=severe,
        weighted_fair_value=weighted_fair_value,
        current_price=current_price,
        benchmark_value=benchmark_value,
        stage3_category=stage3_category,
        stage3_verdict=stage3_verdict,
        sector=sector,
        share_count_source=share_count_source,
        share_qc_detail=share_qc_detail,
    )
    patch_required = classification in {"SOURCE_BUG", "SHARE_DENOMINATOR_BUG"}
    if severe:
        detail += f"; remediation classification {classification}"
        if patch_required:
            detail += "; software patch required before trusting fair value"
        else:
            detail += "; no automated software patch safe from target gap alone"
    return {
        "target_benchmark_price": benchmark_value,
        "fair_value_target_gap_pct": round(gap_pct, 2),
        "fair_value_target_alignment": "SEVERE_MISALIGNMENT" if severe else "ALIGNED",
        "software_patch_required": "TRUE" if patch_required else "FALSE",
        "fair_value_target_gap_detail": detail,
    }


def _parse_pipe_text(text: str) -> List[str]:
    return [part.strip() for part in str(text or "").split("|") if part.strip()]


def _populate_stage2_state(analysis: TickerAnalysis, row: dict) -> None:
    bad_text = _get_kills_text(row)
    parsed_kills = _parse_pipe_text(bad_text)
    raw_bad_count = row.get("stage2_bad_count")
    bad_count = int(float(raw_bad_count)) if raw_bad_count not in (None, "") else None

    if bad_count is None:
        analysis.stage2_kills = parsed_kills
    elif parsed_kills and len(parsed_kills) == bad_count:
        analysis.stage2_kills = parsed_kills
    elif bad_count > 0:
        analysis.stage2_kills = parsed_kills if len(parsed_kills) >= bad_count else ["kill"] * bad_count
    else:
        analysis.stage2_kills = []

    flags_text = _get_flags_text(row)
    analysis.stage2_flags = _parse_pipe_text(flags_text)
    analysis.stage2_tier = _get_tier(row)
    analysis.stage2_score = float(row.get("stage2_score", 0.0) or 0.0)
    analysis.stage2_hp_left = int(float(row.get("stage2_hp_left", 0) or 0))
    analysis.stage2_verdict = row.get("stage2_verdict", "")
    analysis.eligible_for_stage3 = True


def _analysis_from_stage2_row(row: dict, http: HTTP, *, offline_input_only: bool = False) -> TickerAnalysis:
    symbol = row["symbol"].strip().upper()

    if offline_input_only:
        q = QuoteSnapshot(
            symbol=symbol,
            price=_float(row, "price", "price_proxy", "previous_close"),
            sector=row.get("sector") or None,
            industry=row.get("industry") or None,
            market_cap=_float(row, "market_cap"),
            volume=_float(row, "share_volume"),
            target_price=_float(row, "one_yr_target"),
        )
        sec = None
    else:
        finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
        q = parse_finviz_quote(finviz_html, symbol)
        sec = load_sec_companyfacts(http, symbol)

    analysis = TickerAnalysis(
        symbol=symbol,
        quote=q,
        barchart=BarchartSnapshot(),
        options=OptionsSnapshot(),
    )
    analysis.stage1_pass = True
    _populate_stage2_state(analysis, row)
    analysis.sec = sec
    return analysis


def _fieldnames() -> List[str]:
    return [
        "symbol",
        "stage2_tier",
        "stage2_score",
        "stage2_hp_left",
        "stage3_verdict",
        "stage3_category",
        "weighted_fair_value",
        "stage2_one_yr_target",
        "finviz_target_price",
        "target_benchmark_price",
        "fair_value_target_gap_pct",
        "fair_value_target_alignment",
        "software_patch_required",
        "fair_value_target_gap_detail",
        "mos_threshold",
        "current_price",
        "undervaluation_pct",
        "bear_value",
        "realistic_value",
        "bull_value",
        "qc_fail_reason",
        "share_count_source",
        "share_qc_detail",
        "watch_signal",
        "kill_signal",
        "stage2_kills",
        "stage2_flags",
        "sector",
        "iv_rank",
        "implied_vol",
    ]


def _failed_analysis(symbol: str, stage2_row: dict, reason: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "stage2_tier": _get_tier(stage2_row),
        "stage2_score": stage2_row.get("stage2_score", ""),
        "stage2_hp_left": stage2_row.get("stage2_hp_left", ""),
        "stage3_verdict": "QC FAIL",
        "stage3_category": "",
        "weighted_fair_value": "",
        "stage2_one_yr_target": _csv_cell(_float(stage2_row, "one_yr_target")),
        "finviz_target_price": "",
        "target_benchmark_price": "",
        "fair_value_target_gap_pct": "",
        "fair_value_target_alignment": "NO_TARGET_CHECK",
        "software_patch_required": "FALSE",
        "fair_value_target_gap_detail": "target check skipped: Stage 3 QC FAIL",
        "mos_threshold": "",
        "current_price": "",
        "undervaluation_pct": "",
        "bear_value": "",
        "realistic_value": "",
        "bull_value": "",
        "qc_fail_reason": reason,
        "share_count_source": "",
        "share_qc_detail": "",
        "watch_signal": "",
        "kill_signal": "",
        "stage2_kills": _get_kills_text(stage2_row),
        "stage2_flags": _get_flags_text(stage2_row),
        "sector": stage2_row.get("sector", ""),
        "iv_rank": "",
        "implied_vol": "",
    }


def _result_row(stage2_row: dict, analysis: TickerAnalysis) -> Dict[str, Any]:
    s3 = analysis.stage3 or {}
    weighted_fair_value = s3.get("weighted_fair_value")
    try:
        weighted_fair_value_float = float(weighted_fair_value) if weighted_fair_value not in (None, "") else None
    except (TypeError, ValueError):
        weighted_fair_value_float = None
    stage2_target = _float(stage2_row, "one_yr_target")
    finviz_target = analysis.quote.target_price
    alignment = _target_alignment(
        weighted_fair_value_float,
        stage2_target,
        finviz_target,
        current_price=s3.get("current_price", analysis.quote.price),
        stage3_category=s3.get("category"),
        stage3_verdict=summary_verdict(analysis),
        sector=stage2_row.get("sector") or analysis.quote.sector,
        share_count_source=s3.get("share_count_source") or s3.get("key_facts", {}).get("shares_source"),
        share_qc_detail=s3.get("share_qc_detail"),
    )
    return {
        "symbol": analysis.symbol,
        "stage2_tier": analysis.stage2_tier or _get_tier(stage2_row),
        "stage2_score": stage2_row.get("stage2_score", analysis.stage2_score),
        "stage2_hp_left": stage2_row.get("stage2_hp_left", analysis.stage2_hp_left),
        "stage3_verdict": summary_verdict(analysis),
        "stage3_category": _csv_cell(s3.get("category")),
        "weighted_fair_value": _csv_cell(weighted_fair_value),
        "stage2_one_yr_target": _csv_cell(stage2_target),
        "finviz_target_price": _csv_cell(finviz_target),
        "target_benchmark_price": _csv_cell(alignment["target_benchmark_price"]),
        "fair_value_target_gap_pct": _csv_cell(alignment["fair_value_target_gap_pct"]),
        "fair_value_target_alignment": alignment["fair_value_target_alignment"],
        "software_patch_required": alignment["software_patch_required"],
        "fair_value_target_gap_detail": alignment["fair_value_target_gap_detail"],
        "mos_threshold": _csv_cell(s3.get("mos_threshold")),
        "current_price": _csv_cell(s3.get("current_price", analysis.quote.price)),
        "undervaluation_pct": _csv_cell(s3.get("undervaluation_pct")),
        "bear_value": _csv_cell(s3.get("bear")),
        "realistic_value": _csv_cell(s3.get("realistic")),
        "bull_value": _csv_cell(s3.get("bull")),
        "qc_fail_reason": _csv_cell(s3.get("qc_fail_reason")),
        "share_count_source": _csv_cell(s3.get("share_count_source") or s3.get("key_facts", {}).get("shares_source")),
        "share_qc_detail": _csv_cell(s3.get("share_qc_detail")),
        "watch_signal": _csv_cell(s3.get("watch_signal")),
        "kill_signal": _csv_cell(s3.get("kill_signal")),
        "stage2_kills": " | ".join(analysis.stage2_kills) or _get_kills_text(stage2_row),
        "stage2_flags": " | ".join(analysis.stage2_flags) or _get_flags_text(stage2_row),
        "sector": stage2_row.get("sector") or analysis.quote.sector or "",
        "iv_rank": stage2_row.get("iv_rank", ""),
        "implied_vol": stage2_row.get("implied_vol", ""),
    }


def _process_stage3_row(row: dict, offline_input_only: bool = False) -> Dict[str, Any]:
    symbol = (row.get("symbol") or "").strip().upper()
    http = HTTP(timeout=10, retries=1)
    analysis = _analysis_from_stage2_row(row, http, offline_input_only=offline_input_only)
    s3 = stage3_analysis(analysis)
    if s3 is None:
        return _failed_analysis(symbol, row, "stage3_analysis returned None")
    analysis.stage3 = s3
    return _result_row(row, analysis)


def _sort_key(row: Dict[str, Any]) -> tuple:
    score = 0.0
    try:
        score = float(row.get("stage2_score") or 0.0)
    except ValueError:
        pass
    return (TIER_ORDER.get(str(row.get("stage2_tier", "")), 99), -score, str(row.get("symbol", "")))


def _input_tier_counts(rows: Iterable[dict]) -> Dict[str, int]:
    return dict(Counter(_get_tier(row) for row in rows))


def _write_jsonl(path: Path, events: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _process_tier_rows(rows: List[dict], workers: int, offline_input_only: bool) -> List[Dict[str, Any]]:
    if not rows:
        return []
    results: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(_process_stage3_row, row, offline_input_only): idx for idx, row in enumerate(rows)}
        for future in as_completed(future_map):
            idx = future_map[future]
            row = rows[idx]
            symbol = (row.get("symbol") or "").strip().upper()
            try:
                results[idx] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[idx] = _failed_analysis(symbol, row, str(exc))
    return [results[idx] for idx in range(len(rows))]


def run(
    input_csv_path: Path | str = DEFAULT_INPUT,
    *,
    output_csv_path: Path | str = DEFAULT_OUTPUT,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    workers: int = 2,
    min_verdicts: int = 5,
    tiers: Optional[List[str]] = None,
    offline_input_only: bool = False,
    show_progress: bool = True,
) -> Stage3RunResult:
    start = time.perf_counter()
    input_path = Path(input_csv_path).expanduser().resolve()
    output_path = Path(output_csv_path).expanduser().resolve()
    log_root = Path(log_dir).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_root / f"stage3_run_{timestamp}.log"
    audit_path = log_root / f"stage3_run_{timestamp}.jsonl"

    requested_tiers = tiers or list(DEFAULT_TIERS)
    requested_tiers = [tier.strip() for tier in requested_tiers if tier.strip()]
    rows = _load_stage2_rows(input_path)
    eligible_rows = [row for row in rows if _is_stage3_eligible(row) and _get_tier(row) in requested_tiers]
    input_counts = _input_tier_counts(rows)
    eligible_counts = _input_tier_counts(eligible_rows)

    events: List[Dict[str, Any]] = []
    log_lines = [
        f"Stage 3 run started {timestamp}",
        f"input={input_path}",
        f"output={output_path}",
        f"log={log_path}",
        f"audit_jsonl={audit_path}",
        f"rows={len(rows)}",
        f"eligible_rows={len(eligible_rows)}",
        f"input_tier_counts={json.dumps(input_counts, sort_keys=True)}",
        f"eligible_tier_counts={json.dumps(eligible_counts, sort_keys=True)}",
        f"tiers_requested={requested_tiers}",
        f"min_verdicts={min_verdicts}",
        f"workers={max(1, workers)}",
        f"offline_input_only={offline_input_only}",
    ]
    events.append(
        {
            "event": "stage3_run_start",
            "timestamp": timestamp,
            "input_csv": str(input_path),
            "output_csv": str(output_path),
            "input_rows": len(rows),
            "total_eligible": len(eligible_rows),
            "input_tier_counts": input_counts,
            "eligible_tier_counts": eligible_counts,
            "tiers_requested": requested_tiers,
            "min_verdicts": min_verdicts,
            "workers": max(1, workers),
            "offline_input_only": offline_input_only,
        }
    )

    results: List[Dict[str, Any]] = []
    tiers_consumed: List[str] = []
    cascade_stopped_early = False

    for tier in requested_tiers:
        tier_rows = [row for row in eligible_rows if _get_tier(row) == tier]
        if not tier_rows:
            continue
        tier_start_count = len(results)
        if show_progress:
            print(f"Processing Stage 3 tier {tier}: {len(tier_rows)} symbols", flush=True)
        log_lines.append(f"tier_start tier={tier} symbols={len(tier_rows)}")
        tier_results = _process_tier_rows(tier_rows, workers, offline_input_only)
        results.extend(tier_results)
        tiers_consumed.append(tier)

        for result in tier_results:
            symbol_event = {
                "event": "stage3_symbol_result",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": result.get("symbol"),
                "stage2_tier": result.get("stage2_tier"),
                "stage3_verdict": result.get("stage3_verdict"),
                "stage3_category": result.get("stage3_category"),
                "weighted_fair_value": result.get("weighted_fair_value"),
                "stage2_one_yr_target": result.get("stage2_one_yr_target"),
                "finviz_target_price": result.get("finviz_target_price"),
                "target_benchmark_price": result.get("target_benchmark_price"),
                "fair_value_target_gap_pct": result.get("fair_value_target_gap_pct"),
                "fair_value_target_alignment": result.get("fair_value_target_alignment"),
                "software_patch_required": result.get("software_patch_required"),
                "fair_value_target_gap_detail": result.get("fair_value_target_gap_detail"),
                "mos_threshold": result.get("mos_threshold"),
                "current_price": result.get("current_price"),
                "undervaluation_pct": result.get("undervaluation_pct"),
                "qc_fail_reason": result.get("qc_fail_reason") or None,
            }
            events.append(symbol_event)
            log_line = (
                f"symbol_result symbol={result.get('symbol')} stage2_tier={result.get('stage2_tier')} "
                f"stage3_verdict={result.get('stage3_verdict')} category={result.get('stage3_category')} "
                f"price={result.get('current_price')} fv={result.get('weighted_fair_value')} "
                f"stage2_target={result.get('stage2_one_yr_target')} finviz_target={result.get('finviz_target_price')} "
                f"fv_target_alignment={result.get('fair_value_target_alignment')} "
                f"fv_target_gap_pct={result.get('fair_value_target_gap_pct')} "
                f"software_patch_required={result.get('software_patch_required')} "
                f"mos={result.get('mos_threshold')} qc_fail_reason={result.get('qc_fail_reason')}"
            )
            log_lines.append(log_line)
            if show_progress:
                print(log_line, flush=True)

        actionable_count = sum(1 for result in results if result.get("stage3_verdict") in ACTIONABLE_VERDICTS)
        cumulative_symbols = len(results)
        if min_verdicts > 0 and actionable_count >= min_verdicts:
            decision = "stop"
            reason = f"actionable count {actionable_count} met threshold {min_verdicts}"
            cascade_stopped_early = True
        elif min_verdicts == 0:
            decision = "continue"
            reason = "min_verdicts=0 disables cascade stop"
        else:
            decision = "continue"
            reason = f"actionable count {actionable_count} below threshold {min_verdicts}"
        decision_event = {
            "event": "stage3_cascade_decision",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier_completed": tier,
            "symbols_in_tier": len(tier_results),
            "cumulative_symbols": cumulative_symbols,
            "cumulative_actionable": actionable_count,
            "min_verdicts_threshold": min_verdicts,
            "decision": decision,
            "reason": reason,
        }
        events.append(decision_event)
        decision_line = (
            f"cascade_decision tier_completed={tier} symbols_in_tier={len(tier_results)} "
            f"cumulative_symbols={cumulative_symbols} actionable={actionable_count} decision={decision} reason={reason}"
        )
        log_lines.append(decision_line)
        if show_progress:
            print(decision_line, flush=True)
        if decision == "stop":
            break
        if len(results) == tier_start_count and show_progress:
            print(f"No eligible rows processed for tier {tier}", flush=True)

    rows_out = sorted(results, key=_sort_key)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_fieldnames())
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in _fieldnames()} for row in rows_out])

    verdict_counts = Counter(row.get("stage3_verdict", "") for row in rows_out)
    actionable_count = sum(verdict_counts.get(verdict, 0) for verdict in ACTIONABLE_VERDICTS)
    software_patch_required_symbols = [
        str(row.get("symbol", "")).strip().upper()
        for row in rows_out
        if str(row.get("software_patch_required", "")).strip().upper() == "TRUE"
    ]
    elapsed = round(time.perf_counter() - start, 3)
    summary = {
        "event": "stage3_run_complete",
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "tiers_consumed": tiers_consumed,
        "cascade_stopped_early": cascade_stopped_early,
        "symbols_processed": len(rows_out),
        "verdicts": dict(verdict_counts),
        "actionable_count": actionable_count,
        "software_patch_required_count": len(software_patch_required_symbols),
        "software_patch_required_symbols": software_patch_required_symbols,
        "runtime_seconds": elapsed,
        "output_csv": str(output_path),
    }
    events.append(summary)
    log_lines.append("summary=" + json.dumps(summary, sort_keys=True))
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    _write_jsonl(audit_path, events)

    if show_progress:
        print("Stage 3 report complete")
        print(f"- Output CSV: {output_path}")
        print(f"- Log: {log_path}")
        print(f"- Audit JSONL: {audit_path}")
        print(f"- Verdict counts: {dict(verdict_counts)}")

    return Stage3RunResult(
        input_csv_path=str(input_path),
        output_csv_path=str(output_path),
        log_path=str(log_path),
        audit_jsonl_path=str(audit_path),
        input_rows=len(rows),
        eligible_rows=len(eligible_rows),
        symbols_processed=len(rows_out),
        tiers_consumed=tiers_consumed,
        cascade_stopped_early=cascade_stopped_early,
        verdict_counts=dict(verdict_counts),
        actionable_count=actionable_count,
        elapsed_seconds=elapsed,
    )


def _parse_tiers(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run canonical Stage 3 valuation batch runner")
    parser.add_argument("input_csv", nargs="?", default=str(DEFAULT_INPUT), help="Path to Stage2_Report.csv")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT), help="Where to write Stage3_Report.csv")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Directory for Stage 3 audit logs")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent workers; recommended max 3")
    parser.add_argument("--min-verdicts", type=int, default=5, help="Cascade stops when DIAMOND+ENTRY >= this; 0 processes all requested tiers")
    parser.add_argument("--tiers", default=",".join(DEFAULT_TIERS), help="Comma-separated tier list to process")
    parser.add_argument("--offline-input-only", action="store_true", help="Skip live fetches; contract testing only and likely QC FAIL")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args(argv)
    run(
        args.input_csv,
        output_csv_path=args.output_csv,
        log_dir=args.log_dir,
        workers=args.workers,
        min_verdicts=args.min_verdicts,
        tiers=_parse_tiers(args.tiers),
        offline_input_only=args.offline_input_only,
        show_progress=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
