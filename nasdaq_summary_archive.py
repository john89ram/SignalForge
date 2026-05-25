#!/usr/bin/env python3
"""Scrape the raw Nasdaq quote summary payload for each symbol in the master list.

This is the "no filters, no judgment" version of the scraper.
It pulls the same JSON shape shown in the Nasdaq summary example, flattens the
important fields into a CSV, and also saves the raw JSON payload per symbol so
future filtering can happen locally.

Default input:
- /home/hermes/market-funnel/master_lists/nasdaq_nyse_master_list.csv

Outputs:
- a timestamped snapshot directory
- a flat CSV with one row per symbol
- per-symbol raw JSON files under symbols/<symbol>/
- run_manifest.json for bookkeeping
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Dict, Iterable, List, Optional, Tuple

from screener import HTTP

DEFAULT_INPUT_CSV = "/home/hermes/market-funnel/master_lists/nasdaq_nyse_master_list.csv"
DEFAULT_OUTPUT_DIR = "/home/hermes/market-funnel/nasdaq_summary_archive"
DEFAULT_WORKERS = 4
DEFAULT_RETRIES = 2
DEFAULT_TIMEOUT = 30
NASDAQ_SUMMARY_URL = "https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"


@dataclass
class SymbolRow:
    symbol: str
    exchange: str
    name: str
    cik: str


@dataclass
class SummaryRow:
    symbol: str
    master_exchange: str
    name: str
    cik: str
    api_exchange: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    one_yr_target_raw: Optional[str]
    one_yr_target: Optional[float]
    today_high_raw: Optional[str]
    today_low_raw: Optional[str]
    today_high: Optional[float]
    today_low: Optional[float]
    share_volume_raw: Optional[str]
    share_volume: Optional[float]
    average_volume_raw: Optional[str]
    average_volume: Optional[float]
    previous_close_raw: Optional[str]
    previous_close: Optional[float]
    fifty_two_week_high_raw: Optional[str]
    fifty_two_week_low_raw: Optional[str]
    fifty_two_week_high: Optional[float]
    fifty_two_week_low: Optional[float]
    market_cap_raw: Optional[str]
    market_cap: Optional[float]
    bid_size_raw: Optional[str]
    ask_size_raw: Optional[str]
    url: str
    json_path: str
    status_code: Optional[int]
    ok: bool
    elapsed_seconds: float


@dataclass
class ArchiveRunResult:
    snapshot_dir: str
    csv_path: str
    total_symbols: int
    completed_symbols: int
    ok_symbols: int
    failed_symbols: int
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
            if not symbol:
                continue
            rows.append(
                SymbolRow(
                    symbol=symbol,
                    exchange=(row.get("exchange") or "").strip().upper(),
                    name=(row.get("name") or "").strip(),
                    cik=(row.get("cik") or "").strip(),
                )
            )
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _entry_value(entry: Any) -> Optional[str]:
    if isinstance(entry, dict):
        value = entry.get("value")
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    if entry is None:
        return None
    text = str(entry).strip()
    return text or None


def _parse_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("$", "").strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_range(value: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    if value is None:
        return None, None, None, None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "-"}:
        return None, None, None, None
    if "/" not in text:
        parsed = _parse_number(text)
        return text, None, parsed, None
    high_raw, low_raw = [part.strip() for part in text.split("/", 1)]
    return high_raw or None, low_raw or None, _parse_number(high_raw), _parse_number(low_raw)


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


def _make_summary_row(symbol: SymbolRow, payload: Dict[str, Any], *, url: str, json_path: str, status_code: Optional[int], elapsed_seconds: float) -> SummaryRow:
    data = payload.get("data") or {}
    summary = data.get("summaryData") or {}
    bid_ask = data.get("bidAsk") or {}

    api_exchange = _entry_value(summary.get("Exchange"))
    sector = _entry_value(summary.get("Sector"))
    industry = _entry_value(summary.get("Industry"))
    one_yr_target_raw = _entry_value(summary.get("OneYrTarget"))
    today_high_low_raw = _entry_value(summary.get("TodayHighLow"))
    share_volume_raw = _entry_value(summary.get("ShareVolume"))
    average_volume_raw = _entry_value(summary.get("AverageVolume"))
    previous_close_raw = _entry_value(summary.get("PreviousClose"))
    fifty_two_week_high_low_raw = _entry_value(summary.get("FiftTwoWeekHighLow"))
    market_cap_raw = _entry_value(summary.get("MarketCap"))
    bid_size_raw = _entry_value((bid_ask.get("Bid * Size") if isinstance(bid_ask, dict) else None))
    ask_size_raw = _entry_value((bid_ask.get("Ask * Size") if isinstance(bid_ask, dict) else None))

    today_high_raw, today_low_raw, today_high, today_low = _parse_range(today_high_low_raw)
    fifty_two_week_high_raw, fifty_two_week_low_raw, fifty_two_week_high, fifty_two_week_low = _parse_range(fifty_two_week_high_low_raw)

    return SummaryRow(
        symbol=symbol.symbol,
        master_exchange=symbol.exchange,
        name=symbol.name,
        cik=symbol.cik,
        api_exchange=api_exchange,
        sector=sector,
        industry=industry,
        one_yr_target_raw=one_yr_target_raw,
        one_yr_target=_parse_number(one_yr_target_raw),
        today_high_raw=today_high_raw,
        today_low_raw=today_low_raw,
        today_high=today_high,
        today_low=today_low,
        share_volume_raw=share_volume_raw,
        share_volume=_parse_number(share_volume_raw),
        average_volume_raw=average_volume_raw,
        average_volume=_parse_number(average_volume_raw),
        previous_close_raw=previous_close_raw,
        previous_close=_parse_number(previous_close_raw),
        fifty_two_week_high_raw=fifty_two_week_high_raw,
        fifty_two_week_low_raw=fifty_two_week_low_raw,
        fifty_two_week_high=fifty_two_week_high,
        fifty_two_week_low=fifty_two_week_low,
        market_cap_raw=market_cap_raw,
        market_cap=_parse_number(market_cap_raw),
        bid_size_raw=bid_size_raw,
        ask_size_raw=ask_size_raw,
        url=url,
        json_path=json_path,
        status_code=status_code,
        ok=True,
        elapsed_seconds=elapsed_seconds,
    )


def _archive_symbol(snapshot_dir: Path, symbol: SymbolRow, *, timeout: int, retries: int) -> SummaryRow:
    symbol_dir = snapshot_dir / "symbols" / _safe_symbol(symbol.symbol)
    symbol_dir.mkdir(parents=True, exist_ok=True)
    url = NASDAQ_SUMMARY_URL.format(symbol=symbol.symbol)
    started_at = perf_counter()
    http = HTTP(timeout=timeout, retries=0)
    if hasattr(http, "session") and hasattr(http.session, "headers"):
        http.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nasdaq.com/",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            }
        )

    try:
        response = _fetch_with_retry(
            http,
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nasdaq.com/",
            },
            retries=retries,
        )
        payload = response.json()
        json_path = symbol_dir / "nasdaq_summary.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        row = _make_summary_row(
            symbol,
            payload,
            url=url,
            json_path=str(json_path),
            status_code=getattr(response, "status_code", None),
            elapsed_seconds=perf_counter() - started_at,
        )
        return row
    except Exception as exc:  # noqa: BLE001
        json_path = symbol_dir / "nasdaq_summary.error.txt"
        json_path.write_text(f"URL: {url}\nERROR: {exc}\n", encoding="utf-8")
        return SummaryRow(
            symbol=symbol.symbol,
            master_exchange=symbol.exchange,
            name=symbol.name,
            cik=symbol.cik,
            api_exchange=None,
            sector=None,
            industry=None,
            one_yr_target_raw=None,
            one_yr_target=None,
            today_high_raw=None,
            today_low_raw=None,
            today_high=None,
            today_low=None,
            share_volume_raw=None,
            share_volume=None,
            average_volume_raw=None,
            average_volume=None,
            previous_close_raw=None,
            previous_close=None,
            fifty_two_week_high_raw=None,
            fifty_two_week_low_raw=None,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
            market_cap_raw=None,
            market_cap=None,
            bid_size_raw=None,
            ask_size_raw=None,
            url=url,
            json_path=str(json_path),
            status_code=None,
            ok=False,
            elapsed_seconds=perf_counter() - started_at,
        )


def _write_csv(path: Path, rows: Iterable[SummaryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "master_exchange",
        "name",
        "cik",
        "api_exchange",
        "sector",
        "industry",
        "one_yr_target_raw",
        "one_yr_target",
        "today_high_raw",
        "today_low_raw",
        "today_high",
        "today_low",
        "share_volume_raw",
        "share_volume",
        "average_volume_raw",
        "average_volume",
        "previous_close_raw",
        "previous_close",
        "fifty_two_week_high_raw",
        "fifty_two_week_low_raw",
        "fifty_two_week_high",
        "fifty_two_week_low",
        "market_cap_raw",
        "market_cap",
        "bid_size_raw",
        "ask_size_raw",
        "url",
        "json_path",
        "status_code",
        "ok",
        "elapsed_seconds",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": row.symbol,
                    "master_exchange": row.master_exchange,
                    "name": row.name,
                    "cik": row.cik,
                    "api_exchange": row.api_exchange or "",
                    "sector": row.sector or "",
                    "industry": row.industry or "",
                    "one_yr_target_raw": row.one_yr_target_raw or "",
                    "one_yr_target": "" if row.one_yr_target is None else row.one_yr_target,
                    "today_high_raw": row.today_high_raw or "",
                    "today_low_raw": row.today_low_raw or "",
                    "today_high": "" if row.today_high is None else row.today_high,
                    "today_low": "" if row.today_low is None else row.today_low,
                    "share_volume_raw": row.share_volume_raw or "",
                    "share_volume": "" if row.share_volume is None else row.share_volume,
                    "average_volume_raw": row.average_volume_raw or "",
                    "average_volume": "" if row.average_volume is None else row.average_volume,
                    "previous_close_raw": row.previous_close_raw or "",
                    "previous_close": "" if row.previous_close is None else row.previous_close,
                    "fifty_two_week_high_raw": row.fifty_two_week_high_raw or "",
                    "fifty_two_week_low_raw": row.fifty_two_week_low_raw or "",
                    "fifty_two_week_high": "" if row.fifty_two_week_high is None else row.fifty_two_week_high,
                    "fifty_two_week_low": "" if row.fifty_two_week_low is None else row.fifty_two_week_low,
                    "market_cap_raw": row.market_cap_raw or "",
                    "market_cap": "" if row.market_cap is None else row.market_cap,
                    "bid_size_raw": row.bid_size_raw or "",
                    "ask_size_raw": row.ask_size_raw or "",
                    "url": row.url,
                    "json_path": row.json_path,
                    "status_code": "" if row.status_code is None else row.status_code,
                    "ok": row.ok,
                    "elapsed_seconds": f"{row.elapsed_seconds:.4f}",
                }
            )


def run_nasdaq_summary_archive(
    input_csv: str = DEFAULT_INPUT_CSV,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    *,
    limit: Optional[int] = None,
    workers: int = DEFAULT_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    csv_path: Optional[str] = None,
) -> ArchiveRunResult:
    started_at = perf_counter()
    symbols = _read_master_list(input_csv, limit=limit)

    snapshot_dir = Path(output_dir).expanduser() / _timestamp()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    output_csv = Path(csv_path).expanduser() if csv_path else snapshot_dir / "nasdaq_summary.csv"

    completed_symbols = 0
    ok_symbols = 0
    failed_symbols = 0
    results: List[SummaryRow] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(_archive_symbol, snapshot_dir, symbol, timeout=timeout, retries=retries): symbol for symbol in symbols}
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            completed_symbols += 1
            if row.ok:
                ok_symbols += 1
            else:
                failed_symbols += 1
            if completed_symbols == len(symbols) or completed_symbols % 100 == 0:
                print(f"Archived {completed_symbols}/{len(symbols)} Nasdaq summary rows", flush=True)

    results.sort(key=lambda row: row.symbol)
    _write_csv(output_csv, results)

    run_manifest = {
        "input_csv": input_csv,
        "output_dir": str(snapshot_dir),
        "csv_path": str(output_csv),
        "total_symbols": len(symbols),
        "completed_symbols": completed_symbols,
        "ok_symbols": ok_symbols,
        "failed_symbols": failed_symbols,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(perf_counter() - started_at, 4),
    }
    (snapshot_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return ArchiveRunResult(
        snapshot_dir=str(snapshot_dir),
        csv_path=str(output_csv),
        total_symbols=len(symbols),
        completed_symbols=completed_symbols,
        ok_symbols=ok_symbols,
        failed_symbols=failed_symbols,
        elapsed_seconds=perf_counter() - started_at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Nasdaq summary JSON for the Nasdaq+NYSE master list")
    parser.add_argument("--input-csv", default=DEFAULT_INPUT_CSV, help=f"Master list CSV input (default: {DEFAULT_INPUT_CSV})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Snapshot root directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--csv-path", help="Optional direct output CSV path (defaults to snapshot_dir/nasdaq_summary.csv)")
    parser.add_argument("--limit", type=int, help="Archive only the first N symbols (useful for smoke tests)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallel symbol workers (default: {DEFAULT_WORKERS})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help=f"Retry count for transient fetch errors (default: {DEFAULT_RETRIES})")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_nasdaq_summary_archive(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        limit=args.limit,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        csv_path=args.csv_path,
    )

    print("Nasdaq summary archive complete")
    print(f"- Snapshot dir: {result.snapshot_dir}")
    print(f"- CSV path: {result.csv_path}")
    print(f"- Symbols archived: {result.completed_symbols}/{result.total_symbols}")
    print(f"- OK: {result.ok_symbols}")
    print(f"- Failed: {result.failed_symbols}")
    print(f"- Runtime: {result.elapsed_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
