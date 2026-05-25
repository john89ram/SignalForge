#!/usr/bin/env python3
"""Stage 1 / Step 2: split rough survivors by exchange.

This step consumes the Stage 1 Step 1 rough survivor CSV and writes exactly two
batch files for downstream enrichment:

- NYSE
- NASDAQ

The split is for workflow batching only. It is not an eligibility filter and it
must preserve every Step 1 survivor unless an unknown exchange is explicitly
reported as an error.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Optional

DEFAULT_INPUT_CSV = "stages/stage1/output/stage1_step1_rough_filter.csv"
DEFAULT_OUTPUT_DIR = "stages/stage1/output/exchange_splits"
DEFAULT_AUDIT_LOG = "stages/stage1/audit_logs/stage1_step2_exchange_split.jsonl"
EXPECTED_EXCHANGES = ("NYSE", "NASDAQ")


@dataclass(frozen=True)
class ExchangeSplitResult:
    input_csv_path: str
    output_dir: str
    audit_log_path: str
    input_rows: int
    nyse_rows: int
    nasdaq_rows: int
    unknown_rows: int
    nyse_csv_path: str
    nasdaq_csv_path: str
    runtime_seconds: float


def normalize_exchange(value: Optional[str]) -> str:
    text = (value or "").strip().upper()
    if text.startswith("NYSE"):
        return "NYSE"
    if text.startswith("NASDAQ"):
        return "NASDAQ"
    return text or "UNKNOWN"


def split_rows_by_exchange(rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    grouped = {exchange: [] for exchange in EXPECTED_EXCHANGES}
    unknown_rows: list[dict[str, str]] = []
    for row in rows:
        exchange = normalize_exchange(row.get("master_exchange") or row.get("exchange") or row.get("api_exchange"))
        if exchange in grouped:
            grouped[exchange].append(row)
        else:
            unknown_rows.append(row)
    return grouped, unknown_rows


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _append_audit_log(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def run_stage1_step2_exchange_split(
    *,
    input_csv_path: str = DEFAULT_INPUT_CSV,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    audit_log_path: str = DEFAULT_AUDIT_LOG,
    fail_on_unknown: bool = True,
) -> ExchangeSplitResult:
    started_at = perf_counter()
    input_path = Path(input_csv_path).expanduser()
    output_path = Path(output_dir).expanduser()
    audit_path = Path(audit_log_path).expanduser()

    with input_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    grouped, unknown_rows = split_rows_by_exchange(rows)
    if unknown_rows and fail_on_unknown:
        unknown_symbols = [row.get("symbol", "") for row in unknown_rows[:25]]
        raise ValueError(f"Unknown exchange rows found: {len(unknown_rows)}; examples={unknown_symbols}")

    nyse_csv = output_path / "NYSE.csv"
    nasdaq_csv = output_path / "NASDAQ.csv"
    _write_csv(nyse_csv, grouped["NYSE"], fieldnames)
    _write_csv(nasdaq_csv, grouped["NASDAQ"], fieldnames)

    runtime_seconds = perf_counter() - started_at
    result = ExchangeSplitResult(
        input_csv_path=str(input_path),
        output_dir=str(output_path),
        audit_log_path=str(audit_path),
        input_rows=len(rows),
        nyse_rows=len(grouped["NYSE"]),
        nasdaq_rows=len(grouped["NASDAQ"]),
        unknown_rows=len(unknown_rows),
        nyse_csv_path=str(nyse_csv),
        nasdaq_csv_path=str(nasdaq_csv),
        runtime_seconds=runtime_seconds,
    )

    _append_audit_log(
        audit_path,
        {
            "event": "stage1_step2_exchange_split_complete",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "input_csv_path": result.input_csv_path,
            "output_dir": result.output_dir,
            "input_rows": result.input_rows,
            "nyse_rows": result.nyse_rows,
            "nasdaq_rows": result.nasdaq_rows,
            "unknown_rows": result.unknown_rows,
            "nyse_csv_path": result.nyse_csv_path,
            "nasdaq_csv_path": result.nasdaq_csv_path,
            "runtime_seconds": round(result.runtime_seconds, 4),
            "purpose": "Split Stage 1 Step 1 rough survivors into exchange batches for data enrichment.",
        },
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 Step 2 exchange split")
    parser.add_argument("--input-csv", default=DEFAULT_INPUT_CSV, help="Stage 1 Step 1 rough survivor CSV")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory to write NYSE.csv and NASDAQ.csv")
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG, help="JSONL audit log path")
    parser.add_argument("--allow-unknown", action="store_true", help="Write known exchanges even if unknown exchange rows exist")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_stage1_step2_exchange_split(
        input_csv_path=args.input_csv,
        output_dir=args.output_dir,
        audit_log_path=args.audit_log,
        fail_on_unknown=not args.allow_unknown,
    )
    print("Stage 1 Step 2 exchange split complete")
    print(f"- Input rows: {result.input_rows}")
    print(f"- NYSE rows: {result.nyse_rows}")
    print(f"- NASDAQ rows: {result.nasdaq_rows}")
    print(f"- Unknown rows: {result.unknown_rows}")
    print(f"- NYSE CSV: {result.nyse_csv_path}")
    print(f"- NASDAQ CSV: {result.nasdaq_csv_path}")
    print(f"- Audit log: {result.audit_log_path}")
    print(f"- Runtime seconds: {result.runtime_seconds:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
