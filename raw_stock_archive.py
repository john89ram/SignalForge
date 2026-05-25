#!/usr/bin/env python3
"""Capture a raw per-stock archive for the Nasdaq + NYSE master universe.

This script is intentionally boring:
- no screening
- no filtering
- no ranking
- just raw source payloads, saved verbatim

For each symbol in the input master list, it fetches the raw response bodies from
all configured public sources and writes them into a timestamped snapshot tree.
A manifest CSV and per-symbol JSON manifest make the archive easy to resume and
inspect later.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Dict, Iterable, List, Optional

from screener import HTTP

DEFAULT_INPUT_CSV = "/home/hermes/market-funnel/master_lists/nasdaq_nyse_master_list.csv"
DEFAULT_OUTPUT_DIR = "/home/hermes/market-funnel/raw_stock_archive"
DEFAULT_WORKERS = 3
DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 30

NASDAQ_SUMMARY_URL = "https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"
BARCHART_OVERVIEW_URL = "https://www.barchart.com/stocks/quotes/{symbol}/overview"
FINVIZ_QUOTE_URL = "https://finviz.com/quote.ashx?t={symbol}"
FINVIZ_OPTIONS_URL = "https://finviz.com/quote.ashx?t={symbol}&ta=1&p=d&ty=oc"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/{cik}.json"

DEFAULT_SOURCES = ("nasdaq_summary", "barchart_overview", "finviz_quote", "finviz_options", "sec_companyfacts")

SOURCE_DEFINITIONS = {
    "nasdaq_summary": {
        "url": NASDAQ_SUMMARY_URL,
        "suffix": ".json",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nasdaq.com/",
        },
    },
    "barchart_overview": {
        "url": BARCHART_OVERVIEW_URL,
        "suffix": ".html",
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.barchart.com/",
        },
    },
    "finviz_quote": {
        "url": FINVIZ_QUOTE_URL,
        "suffix": ".html",
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://finviz.com/",
        },
    },
    "finviz_options": {
        "url": FINVIZ_OPTIONS_URL,
        "suffix": ".html",
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://finviz.com/",
        },
    },
    "sec_companyfacts": {
        "url": SEC_COMPANYFACTS_URL,
        "suffix": ".json",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.sec.gov/",
            "User-Agent": "Jonathan Ramirez jonathan@example.com",
        },
    },
}


@dataclass
class SymbolRow:
    symbol: str
    exchange: str
    name: str
    cik: str


@dataclass
class FetchRecord:
    source: str
    url: str
    path: str
    ok: bool
    status_code: Optional[int]
    content_type: Optional[str]
    bytes_written: int
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


@dataclass
class SymbolArchiveResult:
    symbol: str
    exchange: str
    cik: str
    symbol_dir: str
    ok_sources: int
    total_sources: int
    records: List[FetchRecord]
    elapsed_seconds: float


@dataclass
class ArchiveRunResult:
    snapshot_dir: str
    manifest_csv: str
    total_symbols: int
    completed_symbols: int
    ok_sources: int
    failed_sources: int
    elapsed_seconds: float


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "-").replace(" ", "_")


def _read_master_list(input_csv: str, limit: Optional[int] = None) -> List[SymbolRow]:
    rows: List[SymbolRow] = []
    with open(input_csv, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            exchange = (row.get("exchange") or "").strip().upper()
            name = (row.get("name") or "").strip()
            cik = (row.get("cik") or "").strip()
            if not symbol:
                continue
            rows.append(SymbolRow(symbol=symbol, exchange=exchange, name=name, cik=cik))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _fetch_with_retry(http: HTTP, url: str, *, headers: Optional[Dict[str, str]] = None, retries: int = DEFAULT_RETRIES):
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return http.session.get(url, timeout=http.timeout, headers=headers)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"GET failed for {url}: {last_exc}")


def _write_text(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8", errors="replace")
    path.write_bytes(data)
    return len(data)


def _fetch_source(http: HTTP, symbol: SymbolRow, source: str, symbol_dir: Path, *, retries: int) -> FetchRecord:
    definition = SOURCE_DEFINITIONS[source]
    url = definition["url"].format(symbol=symbol.symbol, cik=f"CIK{int(symbol.cik):010d}" if symbol.cik else "")
    suffix = definition["suffix"]
    headers = dict(definition.get("headers", {}))

    started_at = perf_counter()
    try:
        response = _fetch_with_retry(http, url, headers=headers, retries=retries)
        content_type = response.headers.get("content-type")
        filename = f"{source}{suffix}"
        path = symbol_dir / filename
        bytes_written = _write_text(path, response.text)
        elapsed = perf_counter() - started_at
        return FetchRecord(
            source=source,
            url=url,
            path=str(path),
            ok=True,
            status_code=getattr(response, "status_code", None),
            content_type=content_type,
            bytes_written=bytes_written,
            elapsed_seconds=elapsed,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = perf_counter() - started_at
        error_path = symbol_dir / f"{source}.error.txt"
        error_text = f"URL: {url}\nERROR: {exc}\n"
        bytes_written = _write_text(error_path, error_text)
        return FetchRecord(
            source=source,
            url=url,
            path=str(error_path),
            ok=False,
            status_code=None,
            content_type=None,
            bytes_written=bytes_written,
            error=str(exc),
            elapsed_seconds=elapsed,
        )


def _archive_symbol(snapshot_dir: Path, row: SymbolRow, sources: Iterable[str], *, workers: int, timeout: int, retries: int) -> SymbolArchiveResult:
    started_at = perf_counter()
    symbol_dir = snapshot_dir / "symbols" / _safe_symbol(row.symbol)
    symbol_dir.mkdir(parents=True, exist_ok=True)

    http = HTTP(timeout=timeout, retries=0)
    http.session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})

    # Per-symbol manifest input for easy inspection.
    base_manifest = {
        "symbol": row.symbol,
        "exchange": row.exchange,
        "name": row.name,
        "cik": row.cik,
        "sources": list(sources),
        "archived_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol_dir": str(symbol_dir),
    }

    if workers <= 1:
        records = [_fetch_source(http, row, source, symbol_dir, retries=retries) for source in sources]
    else:
        records = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_fetch_source, http, row, source, symbol_dir, retries=retries): source for source in sources}
            for future in as_completed(futures):
                records.append(future.result())
        records.sort(key=lambda r: r.source)

    ok_sources = sum(1 for rec in records if rec.ok)
    manifest = dict(base_manifest)
    manifest["records"] = [
        {
            "source": rec.source,
            "url": rec.url,
            "path": rec.path,
            "ok": rec.ok,
            "status_code": rec.status_code,
            "content_type": rec.content_type,
            "bytes_written": rec.bytes_written,
            "error": rec.error,
            "elapsed_seconds": round(rec.elapsed_seconds, 4),
        }
        for rec in records
    ]
    manifest["ok_sources"] = ok_sources
    manifest["total_sources"] = len(records)
    manifest["elapsed_seconds"] = round(perf_counter() - started_at, 4)

    _write_text(symbol_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return SymbolArchiveResult(
        symbol=row.symbol,
        exchange=row.exchange,
        cik=row.cik,
        symbol_dir=str(symbol_dir),
        ok_sources=ok_sources,
        total_sources=len(records),
        records=records,
        elapsed_seconds=perf_counter() - started_at,
    )


def run_raw_archive(
    input_csv: str = DEFAULT_INPUT_CSV,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    *,
    limit: Optional[int] = None,
    workers: int = DEFAULT_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    sources: Iterable[str] = DEFAULT_SOURCES,
) -> ArchiveRunResult:
    started_at = perf_counter()
    rows = _read_master_list(input_csv, limit=limit)
    sources = tuple(sources)

    snapshot_dir = Path(output_dir).expanduser() / _timestamp()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    manifest_csv = snapshot_dir / "manifest.csv"
    completed_symbols = 0
    ok_sources = 0
    failed_sources = 0
    results: List[SymbolArchiveResult] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor, manifest_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "symbol",
            "exchange",
            "cik",
            "symbol_dir",
            "ok_sources",
            "total_sources",
            "elapsed_seconds",
        ])

        futures = {
            executor.submit(_archive_symbol, snapshot_dir, row, sources, workers=1, timeout=timeout, retries=retries): row
            for row in rows
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed_symbols += 1
            ok_sources += result.ok_sources
            failed_sources += (result.total_sources - result.ok_sources)
            writer.writerow([
                result.symbol,
                result.exchange,
                result.cik,
                result.symbol_dir,
                result.ok_sources,
                result.total_sources,
                f"{result.elapsed_seconds:.4f}",
            ])
            fh.flush()

    run_manifest = {
        "input_csv": input_csv,
        "output_dir": str(snapshot_dir),
        "sources": list(sources),
        "total_symbols": len(rows),
        "completed_symbols": completed_symbols,
        "ok_sources": ok_sources,
        "failed_sources": failed_sources,
        "elapsed_seconds": round(perf_counter() - started_at, 4),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_text(snapshot_dir / "run_manifest.json", json.dumps(run_manifest, indent=2, sort_keys=True) + "\n")

    return ArchiveRunResult(
        snapshot_dir=str(snapshot_dir),
        manifest_csv=str(manifest_csv),
        total_symbols=len(rows),
        completed_symbols=completed_symbols,
        ok_sources=ok_sources,
        failed_sources=failed_sources,
        elapsed_seconds=perf_counter() - started_at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive raw per-stock API payloads for Nasdaq + NYSE master list")
    parser.add_argument("--input-csv", default=DEFAULT_INPUT_CSV, help=f"Master list CSV input (default: {DEFAULT_INPUT_CSV})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Snapshot root directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--limit", type=int, help="Archive only the first N symbols (useful for smoke tests)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallel symbol workers (default: {DEFAULT_WORKERS})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help=f"Retry count for transient fetch errors (default: {DEFAULT_RETRIES})")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="Comma-separated source list to archive")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sources = tuple(source.strip() for source in args.sources.split(",") if source.strip())
    result = run_raw_archive(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        limit=args.limit,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        sources=sources,
    )

    print("Raw archive complete")
    print(f"- Snapshot dir: {result.snapshot_dir}")
    print(f"- Manifest CSV: {result.manifest_csv}")
    print(f"- Symbols archived: {result.completed_symbols}/{result.total_symbols}")
    print(f"- Source fetches ok: {result.ok_sources}")
    print(f"- Source fetches failed: {result.failed_sources}")
    print(f"- Runtime: {result.elapsed_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
