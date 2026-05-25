#!/usr/bin/env python3
"""Stage 1 / Step 4: enrich Barchart candidates with options-liquidity fields.

This step consumes the exchange-specific Barchart-enriched CSVs from Step 3,
merges them back into one audit universe, and fills the legacy Stage 1 options
liquidity fields (`options_volume`, `open_interest`, and `atm_bid_ask_spread`).

By default it fetches option-chain data from Finviz. For deterministic
reconciliation against a prior known-good Stage 1 run, pass one or more
`--liquidity-cache-csv` files containing existing `symbol`, `options_volume`,
`open_interest`, and `atm_bid_ask_spread` columns; cache hits avoid live fetches.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping, Optional, Sequence

from screener import HTTP, OptionsSnapshot, parse_finviz_options

DEFAULT_INPUT_DIR = "stages/stage1/output/barchart_enrichment"
DEFAULT_OUTPUT_CSV = "stages/stage1/output/stage1_step4_options_liquidity_enriched.csv"
DEFAULT_AUDIT_LOG = "stages/stage1/audit_logs/stage1_step4_options_liquidity_enrichment.jsonl"
DEFAULT_INPUT_FILES = ("NASDAQ_barchart_enriched.csv", "NYSE_barchart_enriched.csv")
DEFAULT_DELAY_SECONDS = 0.25
FINVIZ_OPTIONS_URL = "https://finviz.com/quote.ashx?t={symbol}&ta=1&p=d&ty=oc"
LIQUIDITY_FIELDS = [
    "options_liquidity_source",
    "options_liquidity_fetch_ok",
    "options_liquidity_fetch_error",
    "options_volume",
    "open_interest",
    "atm_bid_ask_spread",
    "legacy_stage1_market_cap",
    "legacy_stage1_reasons",
    "options_liquidity_missing_fields",
]
REQUIRED_LIQUIDITY_FIELDS = ("options_volume", "open_interest")


@dataclass(frozen=True)
class Stage1Step4LiquidityResult:
    input_dir: str
    output_csv_path: str
    audit_log_path: str
    total_input_rows: int
    cache_hit_rows: int
    fetched_rows: int
    missing_rows: int
    runtime_seconds: float


def _load_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    all_fields = list(dict.fromkeys(list(fieldnames) + LIQUIDITY_FIELDS))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_audit(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(payload), sort_keys=True) + "\n")


def _has_value(value: object) -> bool:
    text = "" if value is None else str(value).strip()
    return bool(text) and text.upper() not in {"NA", "N/A", "NONE", "NULL", "-"}


def _missing_fields(row: Mapping[str, object]) -> list[str]:
    return [field for field in REQUIRED_LIQUIDITY_FIELDS if not _has_value(row.get(field))]


def _format_int(value: Optional[int]) -> str:
    return "" if value is None else str(int(value))


def _format_float(value: Optional[float]) -> str:
    return "" if value is None else str(float(value))


def _price_for_options(row: Mapping[str, str]) -> Optional[float]:
    for field in ("price_proxy", "previous_close", "price"):
        value = row.get(field)
        if not value:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def load_liquidity_cache(paths: Sequence[str]) -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        rows, _ = _load_csv(path)
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if any(_has_value(row.get(field)) for field in ("options_volume", "open_interest", "atm_bid_ask_spread")):
                cache[symbol] = {
                    "options_volume": row.get("options_volume", ""),
                    "open_interest": row.get("open_interest", ""),
                    "atm_bid_ask_spread": row.get("atm_bid_ask_spread", ""),
                    "legacy_stage1_market_cap": row.get("market_cap", ""),
                    "legacy_stage1_reasons": row.get("stage1_reasons", ""),
                }
    return cache


def fetch_options_snapshot(symbol: str, price: Optional[float], http: Optional[HTTP] = None) -> tuple[Optional[OptionsSnapshot], str]:
    http = http or HTTP(retries=2)
    try:
        html = http.get(FINVIZ_OPTIONS_URL.format(symbol=symbol)).text
        return parse_finviz_options(html, price), ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def enrich_rows_with_liquidity(
    rows: list[dict[str, str]],
    *,
    liquidity_cache: Optional[Mapping[str, Mapping[str, str]]] = None,
    fetcher: Callable[[str, Optional[float]], tuple[Optional[OptionsSnapshot], str]] = fetch_options_snapshot,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    show_progress: bool = True,
) -> tuple[list[dict[str, str]], int, int, int]:
    liquidity_cache = liquidity_cache or {}
    enriched: list[dict[str, str]] = []
    cache_hits = 0
    fetched = 0
    total = len(rows)
    for index, source_row in enumerate(rows, start=1):
        row = dict(source_row)
        symbol = (row.get("symbol") or "").strip().upper()
        row["symbol"] = symbol
        cached = liquidity_cache.get(symbol)
        if cached is not None:
            row["options_volume"] = cached.get("options_volume", "")
            row["open_interest"] = cached.get("open_interest", "")
            row["atm_bid_ask_spread"] = cached.get("atm_bid_ask_spread", "")
            row["legacy_stage1_market_cap"] = cached.get("legacy_stage1_market_cap", "")
            row["legacy_stage1_reasons"] = cached.get("legacy_stage1_reasons", "")
            row["options_liquidity_source"] = "cache"
            row["options_liquidity_fetch_ok"] = "TRUE"
            row["options_liquidity_fetch_error"] = ""
            cache_hits += 1
        else:
            snapshot, error = fetcher(symbol, _price_for_options(row))
            row["options_volume"] = _format_int(snapshot.total_volume if snapshot else None)
            row["open_interest"] = _format_int(snapshot.total_open_interest if snapshot else None)
            row["atm_bid_ask_spread"] = _format_float(snapshot.atm_bid_ask_spread if snapshot else None)
            row.setdefault("legacy_stage1_market_cap", "")
            row.setdefault("legacy_stage1_reasons", "")
            row["options_liquidity_source"] = "finviz"
            row["options_liquidity_fetch_ok"] = "TRUE" if snapshot is not None and not error else "FALSE"
            row["options_liquidity_fetch_error"] = error
            fetched += 1
            if delay_seconds > 0 and index < total:
                time.sleep(delay_seconds)
        row["options_liquidity_missing_fields"] = ",".join(_missing_fields(row))
        enriched.append(row)
        if show_progress:
            print(f"OPTIONS liquidity {index}/{total} {symbol} source={row['options_liquidity_source']} missing={row['options_liquidity_missing_fields'] or 'none'}", flush=True)
    missing = sum(1 for row in enriched if _missing_fields(row))
    return enriched, cache_hits, fetched, missing


def run_stage1_step4_options_liquidity_enrichment(
    *,
    input_dir: str = DEFAULT_INPUT_DIR,
    output_csv_path: str = DEFAULT_OUTPUT_CSV,
    audit_log_path: str = DEFAULT_AUDIT_LOG,
    input_files: Sequence[str] = DEFAULT_INPUT_FILES,
    liquidity_cache_csvs: Sequence[str] = (),
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetcher: Callable[[str, Optional[float]], tuple[Optional[OptionsSnapshot], str]] = fetch_options_snapshot,
    show_progress: bool = True,
) -> Stage1Step4LiquidityResult:
    started_at = perf_counter()
    input_path = Path(input_dir).expanduser()
    output_path = Path(output_csv_path).expanduser()
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

    cache = load_liquidity_cache(liquidity_cache_csvs)
    enriched_rows, cache_hits, fetched_rows, missing_rows = enrich_rows_with_liquidity(
        merged_rows,
        liquidity_cache=cache,
        fetcher=fetcher,
        delay_seconds=delay_seconds,
        show_progress=show_progress,
    )
    _write_csv(output_path, enriched_rows, merged_fieldnames)

    result = Stage1Step4LiquidityResult(
        input_dir=str(input_path),
        output_csv_path=str(output_path),
        audit_log_path=str(audit_path),
        total_input_rows=len(enriched_rows),
        cache_hit_rows=cache_hits,
        fetched_rows=fetched_rows,
        missing_rows=missing_rows,
        runtime_seconds=perf_counter() - started_at,
    )
    _append_audit(
        audit_path,
        {
            "event": "stage1_step4_options_liquidity_enrichment_complete",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "input_dir": result.input_dir,
            "input_files": list(input_files),
            "input_counts": input_counts,
            "liquidity_cache_csvs": list(liquidity_cache_csvs),
            "output_csv_path": result.output_csv_path,
            "total_input_rows": result.total_input_rows,
            "cache_hit_rows": result.cache_hit_rows,
            "fetched_rows": result.fetched_rows,
            "missing_rows": result.missing_rows,
            "runtime_seconds": round(result.runtime_seconds, 4),
        },
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1 Step 4 options-liquidity enrichment")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--liquidity-cache-csv", action="append", default=[])
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--quiet", action="store_true", help="Disable per-row progress output")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_stage1_step4_options_liquidity_enrichment(
        input_dir=args.input_dir,
        output_csv_path=args.output_csv,
        audit_log_path=args.audit_log,
        liquidity_cache_csvs=tuple(args.liquidity_cache_csv),
        delay_seconds=args.delay_seconds,
        show_progress=not args.quiet,
    )
    print("Stage 1 Step 4 options-liquidity enrichment finished")
    print(f"- Input rows: {result.total_input_rows}")
    print(f"- Cache-hit rows: {result.cache_hit_rows}")
    print(f"- Live-fetched rows: {result.fetched_rows}")
    print(f"- Missing liquidity rows: {result.missing_rows}")
    print(f"- Output CSV: {result.output_csv_path}")
    print(f"- Audit log: {result.audit_log_path}")
    print(f"- Runtime seconds: {result.runtime_seconds:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
