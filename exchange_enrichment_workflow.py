#!/usr/bin/env python3
"""Exchange-by-exchange enrichment and verification workflow.

This is meant to sit after the raw census + rough mechanical filters:
1. split the narrowed CSV by exchange
2. enrich each exchange file separately
3. verify for missing premium fields
4. rerun the rows with gaps through a slower retry pass

The workflow keeps exchange segmentation as an organizational aid only.
It does not change the trading rules.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import logging
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from screener import HTTP, TickerAnalysis, analyze_stage1_ticker
from pipeline_logging import configure_logging, log_event

DEFAULT_REQUIRED_FIELDS = (
    "price",
    "market_cap",
    "implied_volatility",
    "options_volume",
    "open_interest",
    "atm_bid_ask_spread",
)
DEFAULT_WORKERS = 3
DEFAULT_RETRY_WORKERS = 1
DEFAULT_OUTPUT_DIR = "/tmp/market_cap_exchange_enrichment"
DEFAULT_ENRICHED_SUFFIX = "_enriched.csv"
DEFAULT_REPAIRED_SUFFIX = "_repaired.csv"
DEFAULT_REPORT_NAME = "enrichment_report.csv"
DEFAULT_RETRY_QUEUE_NAME = "retry_queue.csv"
DEFAULT_UNRESOLVED_NAME = "unresolved.csv"
DEFAULT_STAGE1_PASS_NAME = "Stage1_PASS.csv"
DEFAULT_STAGE1_FAIL_NAME = "Stage1_FAIL.csv"


@dataclasses.dataclass
class ExchangeEnrichmentFileResult:
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    output_rows: int
    runtime_seconds: float


@dataclasses.dataclass
class ExchangeVerificationFileResult:
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    missing_rows: int
    repaired_rows: int
    unresolved_rows: int
    runtime_seconds: float


@dataclasses.dataclass
class ExchangeWorkflowResult:
    input_dir: str
    output_dir: str
    mode: str
    enriched_files: List[str]
    repaired_files: List[str]
    report_csv_path: str
    retry_queue_csv_path: str
    unresolved_csv_path: str
    stage1_pass_csv_path: str
    stage1_fail_csv_path: str
    runtime_seconds: float


_tls = threading.local()


def _get_http() -> HTTP:
    if not hasattr(_tls, "http"):
        _tls.http = HTTP(retries=3)
    return _tls.http


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _load_csv_rows(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: str, rows: List[dict], fieldnames: Sequence[str]) -> None:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
        if fieldnames:
            writer.writeheader()
            writer.writerows(rows)


def _exchange_name_from_path(input_csv_path: str) -> str:
    return Path(input_csv_path).stem.upper()


def _stage1_passed(value: object) -> bool:
    text = str(value).strip().upper()
    return text in {"PASS", "TRUE", "1", "YES", "Y"}


def _stage1_output_paths(output_dir: str) -> Tuple[str, str]:
    base = Path(output_dir).expanduser()
    return str(base / DEFAULT_STAGE1_PASS_NAME), str(base / DEFAULT_STAGE1_FAIL_NAME)


def collect_stage1_results_csv(
    input_dir: str,
    pass_csv_path: str,
    fail_csv_path: str,
    *,
    prefer_repaired: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Tuple[int, int]:
    base = Path(input_dir).expanduser()
    repaired = sorted(base.glob(f"*{DEFAULT_REPAIRED_SUFFIX}"), key=lambda p: p.name)
    enriched = sorted(base.glob(f"*{DEFAULT_ENRICHED_SUFFIX}"), key=lambda p: p.name)
    source_files = repaired if (prefer_repaired and repaired) else enriched

    pass_rows: List[dict] = []
    fail_rows: List[dict] = []
    fieldnames: List[str] = []

    for source_file in source_files:
        rows = _load_csv_rows(str(source_file))
        for row in rows:
            row = dict(row)
            row.setdefault("source_exchange_file", source_file.name)
            is_pass = _stage1_passed(row.get("stage1_pass", ""))
            if is_pass:
                pass_rows.append(row)
            else:
                fail_rows.append(row)
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)

    pass_rows.sort(key=lambda row: (row.get("symbol", ""), row.get("source_exchange_file", "")))
    fail_rows.sort(key=lambda row: (row.get("symbol", ""), row.get("source_exchange_file", "")))

    if fieldnames:
        _write_csv(pass_csv_path, pass_rows, fieldnames)
        _write_csv(fail_csv_path, fail_rows, fieldnames)
    else:
        _write_csv(pass_csv_path, [], ["symbol"])
        _write_csv(fail_csv_path, [], ["symbol"])

    if logger is not None:
        log_event(
            logger,
            "stage1_results_collected",
            input_dir=str(base),
            source_files=len(source_files),
            pass_csv_path=pass_csv_path,
            fail_csv_path=fail_csv_path,
            pass_rows=len(pass_rows),
            fail_rows=len(fail_rows),
        )

    return len(pass_rows), len(fail_rows)


def parse_required_fields(required_fields: Optional[str]) -> Tuple[str, ...]:
    if not required_fields:
        return DEFAULT_REQUIRED_FIELDS
    fields = [part.strip() for part in required_fields.split(",") if part.strip()]
    return tuple(dict.fromkeys(fields))


def _value_missing(field: str, value: Optional[str]) -> bool:
    text = "" if value is None else str(value).strip()
    if not text:
        return True

    if field in {"price", "market_cap", "implied_volatility", "options_volume", "open_interest", "atm_bid_ask_spread"}:
        cleaned = text.replace(",", "").replace("$", "").replace("%", "")
        m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not m:
            return True
        try:
            return float(m.group(0)) <= 0
        except ValueError:
            return True

    return False


def _missing_fields_for_row(row: dict, required_fields: Sequence[str]) -> List[str]:
    missing = [field for field in required_fields if _value_missing(field, row.get(field))]
    return missing


def _analysis_to_row(
    source_row: dict,
    analysis: Optional[TickerAnalysis],
    *,
    required_fields: Sequence[str],
    fetch_error: str = "",
) -> dict:
    symbol = _normalize_symbol(source_row.get("symbol", ""))
    row = dict(source_row)
    row["symbol"] = symbol
    row.setdefault("exchange", source_row.get("exchange", ""))
    row.setdefault("sector", source_row.get("sector", ""))
    row.setdefault("industry", source_row.get("industry", ""))
    row["source_input_file"] = source_row.get("source_input_file", "")
    row["fetch_error"] = fetch_error

    if analysis is not None:
        q = analysis.quote
        b = analysis.barchart
        o = analysis.options
        if q.price is not None:
            row["price"] = q.price
        if q.market_cap is not None:
            row["market_cap"] = q.market_cap
        if q.sector:
            row["sector"] = q.sector
        if q.industry:
            row["industry"] = q.industry
        row["implied_volatility"] = b.implied_volatility if b.implied_volatility is not None else row.get("implied_volatility", "")
        row["historical_volatility"] = b.historical_volatility if b.historical_volatility is not None else row.get("historical_volatility", "")
        row["iv_percentile"] = b.iv_percentile if b.iv_percentile is not None else row.get("iv_percentile", "")
        row["iv_rank"] = b.iv_rank if b.iv_rank is not None else row.get("iv_rank", "")
        row["expected_move"] = b.expected_move if b.expected_move is not None else row.get("expected_move", "")
        row["options_volume"] = o.total_volume if o.total_volume is not None else row.get("options_volume", "")
        row["open_interest"] = o.total_open_interest if o.total_open_interest is not None else row.get("open_interest", "")
        row["atm_bid_ask_spread"] = o.atm_bid_ask_spread if o.atm_bid_ask_spread is not None else row.get("atm_bid_ask_spread", "")
        row["stage1_pass"] = "PASS" if analysis.stage1_pass else "KILL"
        row["stage1_reasons"] = " | ".join(analysis.stage1_reasons) if analysis.stage1_reasons else ""
    else:
        row.setdefault("implied_volatility", "")
        row.setdefault("historical_volatility", "")
        row.setdefault("iv_percentile", "")
        row.setdefault("iv_rank", "")
        row.setdefault("expected_move", "")
        row.setdefault("options_volume", "")
        row.setdefault("open_interest", "")
        row.setdefault("atm_bid_ask_spread", "")
        row["stage1_pass"] = "KILL"
        row["stage1_reasons"] = fetch_error or "fetch failed"

    row["missing_fields"] = ",".join(_missing_fields_for_row(row, required_fields))
    return row


def fetch_stage1_analysis(
    symbol: str,
    *,
    min_implied_vol: float,
    min_options_volume: int,
    min_market_cap: float,
    min_today_volume: float,
    min_open_interest: int,
    min_price: float,
    max_price: float,
) -> TickerAnalysis:
    http = _get_http()
    return analyze_stage1_ticker(
        http,
        symbol,
        min_implied_vol=min_implied_vol,
        min_options_volume=min_options_volume,
        min_market_cap=min_market_cap,
        min_today_volume=min_today_volume,
        min_open_interest=min_open_interest,
        min_price=min_price,
        max_price=max_price,
    )


@dataclasses.dataclass
class _EnrichContext:
    required_fields: Sequence[str]
    fetch_analysis: Callable[[str], TickerAnalysis]


@dataclasses.dataclass
class _RetryCandidate:
    row: dict
    missing_fields: List[str]


@dataclasses.dataclass
class _WorkerResult:
    source_row: dict
    analysis: Optional[TickerAnalysis]
    fetch_error: str


def _worker_enrich(source_row: dict, ctx: _EnrichContext) -> _WorkerResult:
    symbol = _normalize_symbol(source_row.get("symbol", ""))
    try:
        analysis = ctx.fetch_analysis(symbol)
        return _WorkerResult(source_row=source_row, analysis=analysis, fetch_error="")
    except Exception as exc:  # noqa: BLE001
        return _WorkerResult(source_row=source_row, analysis=None, fetch_error=str(exc))


def enrich_exchange_csv(
    input_csv_path: str,
    output_csv_path: str,
    *,
    fetch_analysis: Callable[[str], TickerAnalysis],
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
    workers: int = DEFAULT_WORKERS,
    logger: Optional[logging.Logger] = None,
) -> ExchangeEnrichmentFileResult:
    started_at = perf_counter()
    rows = _load_csv_rows(input_csv_path)
    exchange_name = _exchange_name_from_path(input_csv_path)
    if logger is not None:
        log_event(logger, "exchange_enrich_start", input_csv_path=input_csv_path, output_csv_path=output_csv_path, input_rows=len(rows), workers=workers)
    if not rows:
        _write_csv(output_csv_path, [], ["rank", "symbol"])
        if logger is not None:
            log_event(logger, "exchange_enrich_complete", input_csv_path=input_csv_path, output_csv_path=output_csv_path, input_rows=0, output_rows=0, runtime_seconds=round(perf_counter() - started_at, 4))
        return ExchangeEnrichmentFileResult(
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=0,
            output_rows=0,
            runtime_seconds=perf_counter() - started_at,
        )

    for row in rows:
        row["source_input_file"] = Path(input_csv_path).name

    ctx = _EnrichContext(required_fields=required_fields, fetch_analysis=fetch_analysis)
    completed: List[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_worker_enrich, row, ctx) for row in rows]
        for index, future in enumerate(futures, start=1):
            worker_result = future.result()
            enriched_row = _analysis_to_row(
                worker_result.source_row,
                worker_result.analysis,
                required_fields=required_fields,
                fetch_error=worker_result.fetch_error,
            )
            completed.append(enriched_row)
            if logger is not None:
                log_event(
                    logger,
                    "exchange_enrich_progress",
                    exchange=exchange_name,
                    input_csv_path=input_csv_path,
                    output_csv_path=output_csv_path,
                    completed_rows=index,
                    total_rows=len(rows),
                    remaining_rows=len(rows) - index,
                    percent_complete=round((index / len(rows)) * 100, 1),
                    current_symbol=enriched_row.get("symbol", ""),
                )

    completed.sort(key=lambda r: (0 if r.get("stage1_pass") == "PASS" else 1, r.get("symbol", "")))
    fieldnames = list(completed[0].keys())
    _write_csv(output_csv_path, completed, fieldnames)
    if logger is not None:
        log_event(
            logger,
            "exchange_enrich_complete",
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=len(rows),
            output_rows=len(completed),
            runtime_seconds=round(perf_counter() - started_at, 4),
        )
    return ExchangeEnrichmentFileResult(
        input_csv_path=input_csv_path,
        output_csv_path=output_csv_path,
        input_rows=len(rows),
        output_rows=len(completed),
        runtime_seconds=perf_counter() - started_at,
    )


def verify_enriched_exchange_csv(
    input_csv_path: str,
    output_csv_path: str,
    *,
    fetch_analysis: Callable[[str], TickerAnalysis],
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
    retry_workers: int = DEFAULT_RETRY_WORKERS,
    logger: Optional[logging.Logger] = None,
) -> ExchangeVerificationFileResult:
    started_at = perf_counter()
    rows = _load_csv_rows(input_csv_path)
    if logger is not None:
        log_event(logger, "exchange_verify_start", input_csv_path=input_csv_path, output_csv_path=output_csv_path, input_rows=len(rows), retry_workers=retry_workers)
    if not rows:
        _write_csv(output_csv_path, [], ["rank", "symbol"])
        if logger is not None:
            log_event(logger, "exchange_verify_complete", input_csv_path=input_csv_path, output_csv_path=output_csv_path, input_rows=0, missing_rows=0, repaired_rows=0, unresolved_rows=0, runtime_seconds=round(perf_counter() - started_at, 4))
        return ExchangeVerificationFileResult(
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=0,
            missing_rows=0,
            repaired_rows=0,
            unresolved_rows=0,
            runtime_seconds=perf_counter() - started_at,
        )

    missing_candidates: List[_RetryCandidate] = []
    for row in rows:
        missing = _missing_fields_for_row(row, required_fields)
        row["missing_fields"] = ",".join(missing)
        if missing:
            missing_candidates.append(_RetryCandidate(row=row, missing_fields=missing))

    repaired_rows: List[dict] = []
    unresolved_rows: List[dict] = []

    if missing_candidates:
        def _retry_fetch(symbol: str) -> TickerAnalysis:
            return fetch_analysis(symbol)

        with ThreadPoolExecutor(max_workers=max(1, retry_workers)) as executor:
            futures = [executor.submit(_worker_enrich, candidate.row, _EnrichContext(required_fields, _retry_fetch)) for candidate in missing_candidates]
            for future, candidate in zip(futures, missing_candidates):
                worker_result = future.result()
                rebuilt_row = _analysis_to_row(
                    candidate.row,
                    worker_result.analysis,
                    required_fields=required_fields,
                    fetch_error=worker_result.fetch_error,
                )
                if rebuilt_row["missing_fields"]:
                    unresolved_rows.append(rebuilt_row)
                else:
                    repaired_rows.append(rebuilt_row)

    # Merge the repaired rows back into the original set.
    repaired_by_symbol = {row["symbol"]: row for row in repaired_rows}
    unresolved_by_symbol = {row["symbol"]: row for row in unresolved_rows}
    final_rows: List[dict] = []
    for row in rows:
        symbol = _normalize_symbol(row.get("symbol", ""))
        if symbol in repaired_by_symbol:
            final_rows.append(repaired_by_symbol[symbol])
        elif symbol in unresolved_by_symbol:
            final_rows.append(unresolved_by_symbol[symbol])
        else:
            final_rows.append(row)

    final_rows.sort(key=lambda r: (0 if r.get("stage1_pass") == "PASS" else 1, r.get("symbol", "")))
    fieldnames = list(final_rows[0].keys())
    _write_csv(output_csv_path, final_rows, fieldnames)
    if logger is not None:
        log_event(
            logger,
            "exchange_verify_complete",
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=len(rows),
            missing_rows=len(missing_candidates),
            repaired_rows=len(repaired_rows),
            unresolved_rows=len(unresolved_rows),
            runtime_seconds=round(perf_counter() - started_at, 4),
        )
    return ExchangeVerificationFileResult(
        input_csv_path=input_csv_path,
        output_csv_path=output_csv_path,
        input_rows=len(rows),
        missing_rows=len(missing_candidates),
        repaired_rows=len(repaired_rows),
        unresolved_rows=len(unresolved_rows),
        runtime_seconds=perf_counter() - started_at,
    )


def _default_exchange_files(input_dir: str) -> List[Path]:
    path = Path(input_dir).expanduser()
    files = [p for p in path.glob("*.csv") if not p.name.endswith((DEFAULT_ENRICHED_SUFFIX, DEFAULT_REPAIRED_SUFFIX))]
    return sorted(files, key=lambda p: p.name)


def _enriched_output_path(output_dir: str, input_csv_path: str) -> str:
    source = Path(input_csv_path)
    return str(Path(output_dir).expanduser() / f"{source.stem}{DEFAULT_ENRICHED_SUFFIX}")


def _repaired_output_path(output_dir: str, input_csv_path: str) -> str:
    source = Path(input_csv_path)
    stem = source.stem
    if stem.endswith("_enriched"):
        stem = stem[: -len("_enriched")]
    return str(Path(output_dir).expanduser() / f"{stem}{DEFAULT_REPAIRED_SUFFIX}")


def _report_path(output_dir: str) -> str:
    return str(Path(output_dir).expanduser() / DEFAULT_REPORT_NAME)


def _retry_queue_path(output_dir: str) -> str:
    return str(Path(output_dir).expanduser() / DEFAULT_RETRY_QUEUE_NAME)


def _unresolved_path(output_dir: str) -> str:
    return str(Path(output_dir).expanduser() / DEFAULT_UNRESOLVED_NAME)


def _summary_rows_from_enrichment(results: List[ExchangeEnrichmentFileResult]) -> List[dict]:
    return [
        {
            "phase": "enrich",
            "input_csv_path": r.input_csv_path,
            "output_csv_path": r.output_csv_path,
            "input_rows": r.input_rows,
            "output_rows": r.output_rows,
            "missing_rows": "",
            "repaired_rows": "",
            "unresolved_rows": "",
            "runtime_seconds": f"{r.runtime_seconds:.4f}",
        }
        for r in results
    ]


def _summary_rows_from_verification(results: List[ExchangeVerificationFileResult]) -> List[dict]:
    return [
        {
            "phase": "verify",
            "input_csv_path": r.input_csv_path,
            "output_csv_path": r.output_csv_path,
            "input_rows": r.input_rows,
            "output_rows": "",
            "missing_rows": r.missing_rows,
            "repaired_rows": r.repaired_rows,
            "unresolved_rows": r.unresolved_rows,
            "runtime_seconds": f"{r.runtime_seconds:.4f}",
        }
        for r in results
    ]


def run_exchange_workflow(
    input_dir: str,
    output_dir: str,
    *,
    mode: str = "full",
    fetch_analysis: Optional[Callable[[str], TickerAnalysis]] = None,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
    workers: int = DEFAULT_WORKERS,
    retry_workers: int = DEFAULT_RETRY_WORKERS,
    logger: Optional[logging.Logger] = None,
) -> ExchangeWorkflowResult:
    started_at = perf_counter()
    fetcher = fetch_analysis or (
        lambda symbol: fetch_stage1_analysis(
            symbol,
            min_implied_vol=75,
            min_options_volume=1000,
            min_market_cap=1e9,
            min_today_volume=1_000_000,
            min_open_interest=1000,
            min_price=10,
            max_price=75,
        )
    )

    input_path = Path(input_dir).expanduser()
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    if logger is not None:
        log_event(logger, "exchange_workflow_start", input_dir=str(input_path), output_dir=str(output_path), mode=mode, workers=workers, retry_workers=retry_workers, required_fields=list(required_fields))

    source_files = _default_exchange_files(input_dir)
    enriched_files: List[str] = []
    repaired_files: List[str] = []
    enrichment_results: List[ExchangeEnrichmentFileResult] = []
    verification_results: List[ExchangeVerificationFileResult] = []
    retry_queue_rows: List[dict] = []
    unresolved_rows: List[dict] = []

    if mode in {"enrich", "full"}:
        for source_file in source_files:
            enriched_path = _enriched_output_path(output_dir, str(source_file))
            result = enrich_exchange_csv(
                str(source_file),
                enriched_path,
                fetch_analysis=fetcher,
                required_fields=required_fields,
                workers=workers,
                logger=logger,
            )
            enrichment_results.append(result)
            enriched_files.append(result.output_csv_path)

    verify_inputs: List[Path]
    if mode == "verify":
        verify_inputs = [p for p in Path(input_dir).expanduser().glob("*_enriched.csv")]
    else:
        verify_inputs = [Path(path) for path in enriched_files]

    if mode in {"verify", "full"}:
        retry_queue_fieldnames = ["exchange_file", "symbol", "missing_fields", "source_input_file"]
        unresolved_fieldnames = ["exchange_file", "symbol", "missing_fields", "source_input_file", "fetch_error"]
        for enriched_file in verify_inputs:
            repaired_path = _repaired_output_path(output_dir, str(enriched_file))
            result = verify_enriched_exchange_csv(
                str(enriched_file),
                repaired_path,
                fetch_analysis=fetcher,
                required_fields=required_fields,
                retry_workers=retry_workers,
                logger=logger,
            )
            verification_results.append(result)
            repaired_files.append(result.output_csv_path)

            # record any missing rows for reporting
            enriched_rows = _load_csv_rows(str(enriched_file))
            for row in enriched_rows:
                missing = _missing_fields_for_row(row, required_fields)
                if missing:
                    retry_queue_rows.append(
                        {
                            "exchange_file": enriched_file.name,
                            "symbol": row.get("symbol", ""),
                            "missing_fields": ",".join(missing),
                            "source_input_file": row.get("source_input_file", ""),
                        }
                    )
            repaired_rows = _load_csv_rows(repaired_path)
            for row in repaired_rows:
                missing = _missing_fields_for_row(row, required_fields)
                if missing:
                    unresolved_rows.append(
                        {
                            "exchange_file": enriched_file.name,
                            "symbol": row.get("symbol", ""),
                            "missing_fields": ",".join(missing),
                            "source_input_file": row.get("source_input_file", ""),
                            "fetch_error": row.get("fetch_error", ""),
                        }
                    )

    report_rows = _summary_rows_from_enrichment(enrichment_results) + _summary_rows_from_verification(verification_results)
    report_path = _report_path(output_dir)
    _write_csv(
        report_path,
        report_rows,
        [
            "phase",
            "input_csv_path",
            "output_csv_path",
            "input_rows",
            "output_rows",
            "missing_rows",
            "repaired_rows",
            "unresolved_rows",
            "runtime_seconds",
        ],
    )

    retry_queue_path = _retry_queue_path(output_dir)
    _write_csv(retry_queue_path, retry_queue_rows, ["exchange_file", "symbol", "missing_fields", "source_input_file"])

    unresolved_path = _unresolved_path(output_dir)
    _write_csv(unresolved_path, unresolved_rows, ["exchange_file", "symbol", "missing_fields", "source_input_file", "fetch_error"])

    stage1_pass_path, stage1_fail_path = _stage1_output_paths(output_dir)
    stage1_pass_rows, stage1_fail_rows = collect_stage1_results_csv(
        output_dir,
        stage1_pass_path,
        stage1_fail_path,
        prefer_repaired=True,
        logger=logger,
    )

    if logger is not None:
        log_event(
            logger,
            "exchange_workflow_complete",
            input_dir=str(input_path),
            output_dir=str(output_path),
            mode=mode,
            enriched_files=len(enriched_files),
            repaired_files=len(repaired_files),
            retry_queue_rows=len(retry_queue_rows),
            unresolved_rows=len(unresolved_rows),
            stage1_pass_rows=stage1_pass_rows,
            stage1_fail_rows=stage1_fail_rows,
            runtime_seconds=round(perf_counter() - started_at, 4),
        )

    return ExchangeWorkflowResult(
        input_dir=str(input_path),
        output_dir=str(output_path),
        mode=mode,
        enriched_files=enriched_files,
        repaired_files=repaired_files,
        report_csv_path=report_path,
        retry_queue_csv_path=retry_queue_path,
        unresolved_csv_path=unresolved_path,
        stage1_pass_csv_path=stage1_pass_path,
        stage1_fail_csv_path=stage1_fail_path,
        runtime_seconds=perf_counter() - started_at,
    )


def _print_workflow_result(result: ExchangeWorkflowResult) -> None:
    print(f"Mode: {result.mode}")
    print(f"Input dir: {result.input_dir}")
    print(f"Output dir: {result.output_dir}")
    print(f"Enriched files: {len(result.enriched_files)}")
    for path in result.enriched_files:
        print(f"- {path}")
    print(f"Repaired files: {len(result.repaired_files)}")
    for path in result.repaired_files:
        print(f"- {path}")
    print(f"Report: {result.report_csv_path}")
    print(f"Retry queue: {result.retry_queue_csv_path}")
    print(f"Unresolved: {result.unresolved_csv_path}")
    print(f"Stage1 PASS: {result.stage1_pass_csv_path}")
    print(f"Stage1 FAIL: {result.stage1_fail_csv_path}")
    print(f"Runtime: {result.runtime_seconds:.2f}s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exchange-by-exchange enrichment and verification workflow")
    parser.add_argument("--mode", choices=("enrich", "verify", "full"), default="full", help="Run just enrichment, just verification, or both")
    parser.add_argument("--input-dir", required=True, help="Directory containing split exchange CSVs or enriched CSVs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Directory for output files (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers for initial enrichment")
    parser.add_argument("--retry-workers", type=int, default=DEFAULT_RETRY_WORKERS, help="Parallel workers for the retry pass")
    parser.add_argument("--required-fields", default=",".join(DEFAULT_REQUIRED_FIELDS), help="Comma-separated fields required to consider a row complete")
    parser.add_argument("--log-level", default="INFO", help="Logging level for JSON drift events")
    parser.add_argument("--log-file", help="Optional JSONL file to write drift logs to")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    required_fields = parse_required_fields(args.required_fields)
    logger = configure_logging(level=args.log_level, log_file=args.log_file)
    result = run_exchange_workflow(
        args.input_dir,
        args.output_dir,
        mode=args.mode,
        required_fields=required_fields,
        workers=args.workers,
        retry_workers=args.retry_workers,
        logger=logger,
    )
    _print_workflow_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
