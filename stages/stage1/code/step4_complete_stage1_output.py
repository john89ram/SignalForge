#!/usr/bin/env python3
"""Stage 1 / Step 4: merge enriched outputs and finish Stage 1 filtering.

This step consumes the exchange-specific Barchart-enriched CSVs from Step 3,
merges them back into one enriched universe, filters for the Stage 1 implied
volatility floor, writes pass/fail artifacts, appends an audit event, and copies
the completed Stage 1 pass CSV into the Stage 2 input folder.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Mapping, Optional, Sequence

DEFAULT_INPUT_DIR = "stages/stage1/output/barchart_enrichment"
DEFAULT_OUTPUT_DIR = "stages/stage1/output"
DEFAULT_STAGE2_INPUT_DIR = "stages/stage2/input"
DEFAULT_AUDIT_LOG = "stages/stage1/audit_logs/stage1_step4_complete_output.jsonl"
DEFAULT_MIN_IMPLIED_VOLATILITY = 75.0
DEFAULT_INPUT_FILES = ("NASDAQ_barchart_enriched.csv", "NYSE_barchart_enriched.csv")
MERGED_FILENAME = "stage1_step4_merged_barchart_enriched.csv"
PASS_FILENAME = "Stage1_PASS.csv"
FAIL_FILENAME = "Stage1_FAIL.csv"
STEP4_FIELDS = [
    "stage1_step4_implied_volatility",
    "stage1_step4_min_implied_volatility",
    "stage1_step4_verdict",
    "stage1_step4_fail_reason",
]


@dataclass(frozen=True)
class Stage1Step4Result:
    input_dir: str
    output_dir: str
    stage2_input_dir: str
    audit_log_path: str
    merged_csv_path: str
    stage1_pass_csv_path: str
    stage1_fail_csv_path: str
    stage2_input_csv_path: str
    total_input_rows: int
    pass_rows: int
    fail_rows: int
    min_implied_volatility: float
    runtime_seconds: float


def parse_numeric(value: object) -> Optional[float]:
    text = "" if value is None else str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "-"}:
        return None
    cleaned = text.replace(",", "").replace("$", "").replace("%", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _load_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_fields = list(dict.fromkeys(list(fieldnames) + STEP4_FIELDS))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_audit(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(payload), sort_keys=True) + "\n")


def _classify_row(row: dict[str, str], min_implied_volatility: float) -> dict[str, str]:
    enriched = dict(row)
    implied = parse_numeric(enriched.get("barchart_implied_volatility"))
    enriched["stage1_step4_min_implied_volatility"] = str(float(min_implied_volatility))
    if implied is None:
        enriched["stage1_step4_implied_volatility"] = ""
        enriched["stage1_step4_verdict"] = "FAIL"
        enriched["stage1_step4_fail_reason"] = "missing_implied_volatility"
        return enriched

    enriched["stage1_step4_implied_volatility"] = str(implied)
    if implied < min_implied_volatility:
        enriched["stage1_step4_verdict"] = "FAIL"
        enriched["stage1_step4_fail_reason"] = f"implied_volatility_below_{float(min_implied_volatility)}"
    else:
        enriched["stage1_step4_verdict"] = "PASS"
        enriched["stage1_step4_fail_reason"] = ""
    return enriched


def run_stage1_step4_complete_output(
    *,
    input_dir: str = DEFAULT_INPUT_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    stage2_input_dir: str = DEFAULT_STAGE2_INPUT_DIR,
    audit_log_path: str = DEFAULT_AUDIT_LOG,
    min_implied_volatility: float = DEFAULT_MIN_IMPLIED_VOLATILITY,
    input_files: Sequence[str] = DEFAULT_INPUT_FILES,
) -> Stage1Step4Result:
    started_at = perf_counter()
    input_path = Path(input_dir).expanduser()
    output_path = Path(output_dir).expanduser()
    stage2_input_path = Path(stage2_input_dir).expanduser()
    audit_path = Path(audit_log_path).expanduser()

    merged_rows: list[dict[str, str]] = []
    merged_fieldnames: list[str] = []
    input_counts: dict[str, int] = {}
    for filename in input_files:
        csv_path = input_path / filename
        rows, fieldnames = _load_csv(csv_path)
        input_counts[filename] = len(rows)
        merged_rows.extend(rows)
        merged_fieldnames = list(dict.fromkeys(merged_fieldnames + fieldnames))

    classified_rows = [_classify_row(row, min_implied_volatility) for row in merged_rows]
    pass_rows = [row for row in classified_rows if row.get("stage1_step4_verdict") == "PASS"]
    fail_rows = [row for row in classified_rows if row.get("stage1_step4_verdict") == "FAIL"]

    merged_csv = output_path / MERGED_FILENAME
    stage1_pass_csv = output_path / PASS_FILENAME
    stage1_fail_csv = output_path / FAIL_FILENAME
    stage2_input_csv = stage2_input_path / PASS_FILENAME

    _write_csv(merged_csv, classified_rows, merged_fieldnames)
    _write_csv(stage1_pass_csv, pass_rows, merged_fieldnames)
    _write_csv(stage1_fail_csv, fail_rows, merged_fieldnames)
    stage2_input_csv.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stage1_pass_csv, stage2_input_csv)

    result = Stage1Step4Result(
        input_dir=str(input_path),
        output_dir=str(output_path),
        stage2_input_dir=str(stage2_input_path),
        audit_log_path=str(audit_path),
        merged_csv_path=str(merged_csv),
        stage1_pass_csv_path=str(stage1_pass_csv),
        stage1_fail_csv_path=str(stage1_fail_csv),
        stage2_input_csv_path=str(stage2_input_csv),
        total_input_rows=len(classified_rows),
        pass_rows=len(pass_rows),
        fail_rows=len(fail_rows),
        min_implied_volatility=float(min_implied_volatility),
        runtime_seconds=perf_counter() - started_at,
    )

    _append_audit(
        audit_path,
        {
            "event": "stage1_step4_complete_output_complete",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "input_dir": result.input_dir,
            "input_files": list(input_files),
            "input_counts": input_counts,
            "output_dir": result.output_dir,
            "stage2_input_dir": result.stage2_input_dir,
            "merged_csv_path": result.merged_csv_path,
            "stage1_pass_csv_path": result.stage1_pass_csv_path,
            "stage1_fail_csv_path": result.stage1_fail_csv_path,
            "stage2_input_csv_path": result.stage2_input_csv_path,
            "min_implied_volatility": result.min_implied_volatility,
            "total_input_rows": result.total_input_rows,
            "pass_rows": result.pass_rows,
            "fail_rows": result.fail_rows,
            "runtime_seconds": round(result.runtime_seconds, 4),
        },
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 Step 4 complete output merge/filter")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stage2-input-dir", default=DEFAULT_STAGE2_INPUT_DIR)
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--min-implied-volatility", type=float, default=DEFAULT_MIN_IMPLIED_VOLATILITY)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_stage1_step4_complete_output(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        stage2_input_dir=args.stage2_input_dir,
        audit_log_path=args.audit_log,
        min_implied_volatility=args.min_implied_volatility,
    )
    print("Stage 1 Step 4 complete output finished")
    print(f"- Input rows: {result.total_input_rows}")
    print(f"- PASS rows: {result.pass_rows}")
    print(f"- FAIL rows: {result.fail_rows}")
    print(f"- IV floor: {result.min_implied_volatility}")
    print(f"- Merged CSV: {result.merged_csv_path}")
    print(f"- Stage 1 PASS CSV: {result.stage1_pass_csv_path}")
    print(f"- Stage 1 FAIL CSV: {result.stage1_fail_csv_path}")
    print(f"- Stage 2 input copy: {result.stage2_input_csv_path}")
    print(f"- Audit log: {result.audit_log_path}")
    print(f"- Runtime seconds: {result.runtime_seconds:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
