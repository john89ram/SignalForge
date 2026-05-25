#!/usr/bin/env python3
"""Stage 1 / Step 3: Barchart enrichment with bounded repair loops.

This step consumes the exchange-split CSVs from Step 2, calls Barchart once per
symbol, writes enriched CSVs, then reviews the results for missing enrichment
fields. Missing rows are retried in small, targeted repair rounds. The default
repair policy is capped at two rounds so the workflow cannot hammer the site in
an unbounded loop.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping, Optional, Sequence

from screener import HTTP, BarchartSnapshot, parse_barchart_overview

DEFAULT_INPUT_DIR = "stages/stage1/output/exchange_splits"
DEFAULT_OUTPUT_DIR = "stages/stage1/output/barchart_enrichment"
DEFAULT_AUDIT_LOG = "stages/stage1/audit_logs/stage1_step3_barchart_enrichment.jsonl"
DEFAULT_MAX_REPAIR_ROUNDS = 2
DEFAULT_DELAY_SECONDS = 0.25
DEFAULT_REQUIRED_FIELDS = (
    "barchart_implied_volatility",
    "barchart_historical_volatility",
    "barchart_iv_percentile",
    "barchart_iv_rank",
)
BARCHART_URL = "https://www.barchart.com/stocks/quotes/{symbol}/overview"
ENRICHMENT_FIELDS = [
    "barchart_url",
    "barchart_fetch_ok",
    "barchart_fetch_round",
    "barchart_fetch_error",
    "barchart_implied_volatility",
    "barchart_historical_volatility",
    "barchart_iv_percentile",
    "barchart_iv_rank",
    "barchart_iv_high",
    "barchart_iv_low",
    "barchart_expected_move",
    "barchart_missing_fields",
]


@dataclass(frozen=True)
class EnrichedExchangeResult:
    exchange: str
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    enriched_rows: int
    initial_missing_rows: int
    final_missing_rows: int
    repair_rounds_run: int


@dataclass(frozen=True)
class BarchartEnrichmentResult:
    input_dir: str
    output_dir: str
    audit_log_path: str
    exchange_results: list[EnrichedExchangeResult]
    total_input_rows: int
    total_enriched_rows: int
    total_initial_missing_rows: int
    total_final_missing_rows: int
    retry_queue_csv_path: str
    unresolved_csv_path: str
    runtime_seconds: float


def parse_required_fields(value: Optional[str]) -> tuple[str, ...]:
    if not value:
        return DEFAULT_REQUIRED_FIELDS
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def _format_optional(value: Optional[float]) -> str:
    return "" if value is None else str(value)


def _value_missing(value: object) -> bool:
    text = "" if value is None else str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "-"}:
        return True
    cleaned = text.replace(",", "").replace("$", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return match is None


def missing_fields(row: Mapping[str, object], required_fields: Sequence[str]) -> list[str]:
    return [field for field in required_fields if _value_missing(row.get(field))]


def fetch_barchart_snapshot(symbol: str, http: Optional[HTTP] = None) -> tuple[Optional[BarchartSnapshot], str]:
    http = http or HTTP(retries=2)
    url = BARCHART_URL.format(symbol=symbol)
    try:
        html = http.get(url).text
        return parse_barchart_overview(html), ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _apply_snapshot(
    source_row: dict[str, str],
    *,
    snapshot: Optional[BarchartSnapshot],
    fetch_error: str,
    fetch_round: int,
    required_fields: Sequence[str],
) -> dict[str, str]:
    row = dict(source_row)
    symbol = (row.get("symbol") or "").strip().upper()
    row["symbol"] = symbol
    row["barchart_url"] = BARCHART_URL.format(symbol=symbol)
    row["barchart_fetch_ok"] = "TRUE" if snapshot is not None and not fetch_error else "FALSE"
    row["barchart_fetch_round"] = str(fetch_round)
    row["barchart_fetch_error"] = fetch_error
    if snapshot is not None:
        row["barchart_implied_volatility"] = _format_optional(snapshot.implied_volatility)
        row["barchart_historical_volatility"] = _format_optional(snapshot.historical_volatility)
        row["barchart_iv_percentile"] = _format_optional(snapshot.iv_percentile)
        row["barchart_iv_rank"] = _format_optional(snapshot.iv_rank)
        row["barchart_iv_high"] = _format_optional(snapshot.iv_high)
        row["barchart_iv_low"] = _format_optional(snapshot.iv_low)
        row["barchart_expected_move"] = _format_optional(snapshot.expected_move)
    else:
        for field in ENRICHMENT_FIELDS:
            row.setdefault(field, "")
    row["barchart_missing_fields"] = ",".join(missing_fields(row, required_fields))
    return row


def _load_csv(path: Path, limit: Optional[int] = None) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        if limit is not None:
            rows = rows[:limit]
        return rows, list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_fields = list(dict.fromkeys(list(fieldnames) + ENRICHMENT_FIELDS))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_audit(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def enrich_rows_with_repair(
    rows: list[dict[str, str]],
    *,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetcher: Callable[[str], tuple[Optional[BarchartSnapshot], str]] = fetch_barchart_snapshot,
    show_progress: bool = True,
    exchange: str = "",
) -> tuple[list[dict[str, str]], int, int, int]:
    enriched: list[dict[str, str]] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        symbol = (row.get("symbol") or "").strip().upper()
        snapshot, error = fetcher(symbol)
        enriched.append(_apply_snapshot(row, snapshot=snapshot, fetch_error=error, fetch_round=0, required_fields=required_fields))
        if show_progress:
            print(f"{exchange or 'BARCHART'} initial {index}/{total} {symbol}", flush=True)
        if delay_seconds > 0 and index < total:
            time.sleep(delay_seconds)

    initial_missing = sum(1 for row in enriched if missing_fields(row, required_fields))
    rounds_run = 0
    for repair_round in range(1, max(0, max_repair_rounds) + 1):
        missing_indexes = [idx for idx, row in enumerate(enriched) if missing_fields(row, required_fields)]
        if not missing_indexes:
            break
        rounds_run = repair_round
        if show_progress:
            print(f"{exchange or 'BARCHART'} repair round {repair_round}: retrying {len(missing_indexes)} rows", flush=True)
        for offset, idx in enumerate(missing_indexes, start=1):
            source_row = enriched[idx]
            symbol = (source_row.get("symbol") or "").strip().upper()
            snapshot, error = fetcher(symbol)
            repaired = _apply_snapshot(source_row, snapshot=snapshot, fetch_error=error, fetch_round=repair_round, required_fields=required_fields)
            enriched[idx] = repaired
            if show_progress:
                print(f"{exchange or 'BARCHART'} repair {repair_round} {offset}/{len(missing_indexes)} {symbol}", flush=True)
            if delay_seconds > 0 and offset < len(missing_indexes):
                time.sleep(delay_seconds)

    final_missing = sum(1 for row in enriched if missing_fields(row, required_fields))
    return enriched, initial_missing, final_missing, rounds_run


def run_stage1_step3_barchart_enrichment(
    *,
    input_dir: str = DEFAULT_INPUT_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    audit_log_path: str = DEFAULT_AUDIT_LOG,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    limit_per_exchange: Optional[int] = None,
    fetcher: Callable[[str], tuple[Optional[BarchartSnapshot], str]] = fetch_barchart_snapshot,
    show_progress: bool = True,
) -> BarchartEnrichmentResult:
    started_at = perf_counter()
    input_path = Path(input_dir).expanduser()
    output_path = Path(output_dir).expanduser()
    audit_path = Path(audit_log_path).expanduser()
    exchange_files = [input_path / "NYSE.csv", input_path / "NASDAQ.csv"]

    exchange_results: list[EnrichedExchangeResult] = []
    retry_rows: list[dict[str, str]] = []
    unresolved_rows: list[dict[str, str]] = []
    retry_fieldnames: list[str] = []

    for exchange_file in exchange_files:
        exchange = exchange_file.stem.upper()
        rows, fieldnames = _load_csv(exchange_file, limit=limit_per_exchange)
        enriched, initial_missing, final_missing, rounds_run = enrich_rows_with_repair(
            rows,
            required_fields=required_fields,
            max_repair_rounds=max_repair_rounds,
            delay_seconds=delay_seconds,
            fetcher=fetcher,
            show_progress=show_progress,
            exchange=exchange,
        )
        out_csv = output_path / f"{exchange}_barchart_enriched.csv"
        _write_csv(out_csv, enriched, fieldnames)
        retry_rows.extend([row for row in enriched if int(row.get("barchart_fetch_round") or 0) > 0])
        unresolved_rows.extend([row for row in enriched if missing_fields(row, required_fields)])
        retry_fieldnames = list(dict.fromkeys(retry_fieldnames + fieldnames + ENRICHMENT_FIELDS))
        exchange_results.append(
            EnrichedExchangeResult(
                exchange=exchange,
                input_csv_path=str(exchange_file),
                output_csv_path=str(out_csv),
                input_rows=len(rows),
                enriched_rows=len(enriched),
                initial_missing_rows=initial_missing,
                final_missing_rows=final_missing,
                repair_rounds_run=rounds_run,
            )
        )

    retry_queue_csv = output_path / "barchart_retry_queue.csv"
    unresolved_csv = output_path / "barchart_unresolved.csv"
    _write_csv(retry_queue_csv, retry_rows, retry_fieldnames or ENRICHMENT_FIELDS)
    _write_csv(unresolved_csv, unresolved_rows, retry_fieldnames or ENRICHMENT_FIELDS)

    result = BarchartEnrichmentResult(
        input_dir=str(input_path),
        output_dir=str(output_path),
        audit_log_path=str(audit_path),
        exchange_results=exchange_results,
        total_input_rows=sum(item.input_rows for item in exchange_results),
        total_enriched_rows=sum(item.enriched_rows for item in exchange_results),
        total_initial_missing_rows=sum(item.initial_missing_rows for item in exchange_results),
        total_final_missing_rows=sum(item.final_missing_rows for item in exchange_results),
        retry_queue_csv_path=str(retry_queue_csv),
        unresolved_csv_path=str(unresolved_csv),
        runtime_seconds=perf_counter() - started_at,
    )

    _append_audit(
        audit_path,
        {
            "event": "stage1_step3_barchart_enrichment_complete",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "input_dir": result.input_dir,
            "output_dir": result.output_dir,
            "required_fields": list(required_fields),
            "max_repair_rounds": max_repair_rounds,
            "delay_seconds": delay_seconds,
            "limit_per_exchange": limit_per_exchange,
            "total_input_rows": result.total_input_rows,
            "total_enriched_rows": result.total_enriched_rows,
            "total_initial_missing_rows": result.total_initial_missing_rows,
            "total_final_missing_rows": result.total_final_missing_rows,
            "retry_queue_csv_path": result.retry_queue_csv_path,
            "unresolved_csv_path": result.unresolved_csv_path,
            "exchange_results": [item.__dict__ for item in exchange_results],
            "runtime_seconds": round(result.runtime_seconds, 4),
        },
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 Step 3 Barchart enrichment")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--required-fields", default=",".join(DEFAULT_REQUIRED_FIELDS))
    parser.add_argument("--max-repair-rounds", type=int, default=DEFAULT_MAX_REPAIR_ROUNDS, help="Maximum missing-data repair rounds; default and cap are 2")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS, help="Delay between Barchart calls")
    parser.add_argument("--limit-per-exchange", type=int, help="Optional smoke-test limit per exchange")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    max_repair_rounds = min(args.max_repair_rounds, DEFAULT_MAX_REPAIR_ROUNDS)
    result = run_stage1_step3_barchart_enrichment(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        audit_log_path=args.audit_log,
        required_fields=parse_required_fields(args.required_fields),
        max_repair_rounds=max_repair_rounds,
        delay_seconds=args.delay_seconds,
        limit_per_exchange=args.limit_per_exchange,
        show_progress=not args.quiet,
    )
    print("Stage 1 Step 3 Barchart enrichment complete")
    print(f"- Input rows: {result.total_input_rows}")
    print(f"- Enriched rows: {result.total_enriched_rows}")
    print(f"- Initial missing rows: {result.total_initial_missing_rows}")
    print(f"- Final missing rows: {result.total_final_missing_rows}")
    for item in result.exchange_results:
        print(f"- {item.exchange}: {item.enriched_rows} rows -> {item.output_csv_path}")
    print(f"- Retry queue: {result.retry_queue_csv_path}")
    print(f"- Unresolved: {result.unresolved_csv_path}")
    print(f"- Audit log: {result.audit_log_path}")
    print(f"- Runtime seconds: {result.runtime_seconds:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
