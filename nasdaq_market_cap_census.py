#!/usr/bin/env python3
"""Fresh Nasdaq screener pull for the raw market-cap census.

This is the step-1 pull the user asked for:
- call api.nasdaq.com
- gather the full screener universe
- keep only rows with Market Cap >= threshold
- write a raw dump plus the filtered >= threshold universe

Why this exists:
The older SEC-ticker-map -> per-symbol summary path was useful, but it made it too hard to
see where data was being lost. The Nasdaq screener endpoint already returns Market Cap for the
whole universe, so it is a better baseline for diagnosing attrition.
"""

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, List, Optional, Tuple

from screener import HTTP
from pipeline_logging import configure_logging, log_event

NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit={limit}&offset={offset}"
DEFAULT_MIN_MARKET_CAP = 1e9
DEFAULT_PAGE_SIZE = 5000
DEFAULT_OUTPUT_DIR = "/tmp/nasdaq_market_cap_census"


@dataclass
class NasdaqScreenerRow:
    symbol: str
    name: str
    lastsale: Optional[str]
    netchange: Optional[str]
    pctchange: Optional[str]
    market_cap_raw: Optional[str]
    market_cap: Optional[float]
    url: Optional[str]


@dataclass
class NasdaqMarketCapCensusResult:
    total_records: int
    fetched_rows: int
    kept_rows: int
    missing_market_cap_rows: int
    below_threshold_rows: int
    output_dir: str
    raw_csv_path: str
    filtered_csv_path: str
    runtime_seconds: float


def _parse_money(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("$", "").strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_screener_page(http: HTTP, *, limit: int, offset: int) -> Tuple[List[Dict[str, object]], int]:
    payload = http.get(
        NASDAQ_SCREENER_URL.format(limit=limit, offset=offset),
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nasdaq.com/",
        },
    ).json()
    data = payload.get("data") or {}
    table = data.get("table") or {}
    rows = table.get("rows") or []
    total_records = int(data.get("totalrecords") or 0)
    return rows, total_records


def fetch_all_screener_rows(
    http: Optional[HTTP] = None,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    show_progress: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Dict[str, object]], int]:
    http = http or HTTP()
    rows: List[Dict[str, object]] = []
    total_records = 0
    offset = 0

    while True:
        page_rows, page_total = fetch_screener_page(http, limit=page_size, offset=offset)
        if page_total:
            total_records = page_total
        if not page_rows:
            break
        rows.extend(page_rows)
        if logger is not None:
            log_event(
                logger,
                "nasdaq_screener_page_fetched",
                offset=offset,
                page_size=page_size,
                rows_fetched=len(page_rows),
                total_records=total_records or page_total or 0,
                rows_total=len(rows),
            )
        offset += page_size
        if show_progress:
            print(f"Fetched {len(rows)}/{total_records or len(rows)} rows from Nasdaq screener", flush=True)
        if total_records and len(rows) >= total_records:
            break

    return rows, total_records


def _to_row(raw: Dict[str, object]) -> NasdaqScreenerRow:
    market_cap_raw = raw.get("marketCap")
    market_cap_text = str(market_cap_raw).strip() if market_cap_raw is not None else None
    return NasdaqScreenerRow(
        symbol=str(raw.get("symbol") or "").strip().upper(),
        name=str(raw.get("name") or "").strip(),
        lastsale=str(raw.get("lastsale") or "").strip() or None,
        netchange=str(raw.get("netchange") or "").strip() or None,
        pctchange=str(raw.get("pctchange") or "").strip() or None,
        market_cap_raw=market_cap_text,
        market_cap=_parse_money(market_cap_text),
        url=str(raw.get("url") or "").strip() or None,
    )


def _write_csv(path: str, rows: Iterable[NasdaqScreenerRow]) -> None:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "symbol",
        "name",
        "lastsale",
        "netchange",
        "pctchange",
        "market_cap_raw",
        "market_cap",
        "url",
    ]
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "symbol": row.symbol,
                "name": row.name,
                "lastsale": row.lastsale or "",
                "netchange": row.netchange or "",
                "pctchange": row.pctchange or "",
                "market_cap_raw": row.market_cap_raw or "",
                "market_cap": "" if row.market_cap is None else row.market_cap,
                "url": row.url or "",
            })


def run_nasdaq_market_cap_census(
    *,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    page_size: int = DEFAULT_PAGE_SIZE,
    show_progress: bool = True,
    http: Optional[HTTP] = None,
    logger: Optional[logging.Logger] = None,
) -> NasdaqMarketCapCensusResult:
    started_at = perf_counter()
    http = http or HTTP()
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    if logger is not None:
        log_event(
            logger,
            "nasdaq_census_start",
            output_dir=str(output_path),
            min_market_cap=min_market_cap,
            page_size=page_size,
        )

    raw_rows, total_records = fetch_all_screener_rows(http, page_size=page_size, show_progress=show_progress, logger=logger)
    parsed_rows = [_to_row(row) for row in raw_rows]

    kept_rows = [row for row in parsed_rows if row.market_cap is not None and row.market_cap >= min_market_cap]
    missing_market_cap_rows = [row for row in parsed_rows if row.market_cap is None]
    below_threshold_rows = [row for row in parsed_rows if row.market_cap is not None and row.market_cap < min_market_cap]

    raw_csv_path = str(output_path / "nasdaq_screener_raw.csv")
    filtered_csv_path = str(output_path / "market_cap_universe_1b.csv")
    _write_csv(raw_csv_path, parsed_rows)
    _write_csv(filtered_csv_path, kept_rows)

    if logger is not None:
        log_event(
            logger,
            "nasdaq_census_complete",
            total_records=total_records or len(parsed_rows),
            fetched_rows=len(parsed_rows),
            kept_rows=len(kept_rows),
            missing_market_cap_rows=len(missing_market_cap_rows),
            below_threshold_rows=len(below_threshold_rows),
            raw_csv_path=raw_csv_path,
            filtered_csv_path=filtered_csv_path,
            runtime_seconds=round(perf_counter() - started_at, 4),
        )

    return NasdaqMarketCapCensusResult(
        total_records=total_records or len(parsed_rows),
        fetched_rows=len(parsed_rows),
        kept_rows=len(kept_rows),
        missing_market_cap_rows=len(missing_market_cap_rows),
        below_threshold_rows=len(below_threshold_rows),
        output_dir=str(output_path),
        raw_csv_path=raw_csv_path,
        filtered_csv_path=filtered_csv_path,
        runtime_seconds=perf_counter() - started_at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fresh Nasdaq screener market-cap census")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Directory for raw and filtered CSV output (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP, help="Minimum market cap to keep (default: 1e9)")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="Rows to request per Nasdaq screener call")
    parser.add_argument("--log-level", default="INFO", help="Logging level for JSON drift events")
    parser.add_argument("--log-file", help="Optional JSONL file to write drift logs to")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logger = configure_logging(level=args.log_level, log_file=args.log_file)

    result = run_nasdaq_market_cap_census(
        output_dir=args.output_dir,
        min_market_cap=args.min_market_cap,
        page_size=args.page_size,
        show_progress=True,
        logger=logger,
    )

    print("Nasdaq screener market-cap census complete")
    print(f"- Total screener rows: {result.total_records}")
    print(f"- Fetched rows: {result.fetched_rows}")
    print(f"- Kept rows >= ${args.min_market_cap:,.0f}: {result.kept_rows}")
    print(f"- Missing market cap rows: {result.missing_market_cap_rows}")
    print(f"- Below-threshold rows: {result.below_threshold_rows}")
    print(f"- Raw CSV: {result.raw_csv_path}")
    print(f"- Filtered CSV: {result.filtered_csv_path}")
    print(f"- Runtime: {result.runtime_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
