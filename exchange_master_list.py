#!/usr/bin/env python3
"""Build a master list of all SEC-listed Nasdaq + NYSE tickers.

This is intended as a durable quarterly refresh source for the market funnel.
It queries the SEC company_tickers_exchange map, filters to Nasdaq and NYSE,
then writes a sorted CSV + plain-text ticker list for downstream workflows.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Optional

from screener import HTTP

SEC_EXCHANGE_MAP_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
DEFAULT_OUTPUT_DIR = "/home/hermes/market-funnel/master_lists"
DEFAULT_CSV_NAME = "nasdaq_nyse_master_list.csv"
DEFAULT_TICKER_NAME = "nasdaq_nyse_master_list.txt"
SEC_USER_AGENT = "Jonathan Ramirez jonathan@example.com"
TARGET_EXCHANGES = {"NASDAQ", "NYSE"}


@dataclass
class MasterListResult:
    output_dir: str
    csv_path: str
    ticker_path: str
    total_listings: int
    kept_listings: int
    exchange_counts: dict[str, int]
    runtime_seconds: float


def _normalize_exchange(raw: str) -> Optional[str]:
    value = (raw or "").strip().upper()
    if value.startswith("NASDAQ"):
        return "NASDAQ"
    if value == "NYSE":
        return "NYSE"
    return None


def _normalize_symbol(raw: str) -> str:
    return (raw or "").strip().upper()


def fetch_master_list(http: Optional[HTTP] = None) -> list[dict[str, str]]:
    http = http or HTTP()
    payload = http.get(
        SEC_EXCHANGE_MAP_URL,
        headers={"User-Agent": SEC_USER_AGENT},
    ).json()

    rows = payload.get("data") or []
    records: list[dict[str, str]] = []
    for row in rows:
        if len(row) < 4:
            continue
        cik, name, ticker, exchange = row[:4]
        normalized_exchange = _normalize_exchange(str(exchange))
        symbol = _normalize_symbol(str(ticker))
        company_name = str(name).strip()
        if not symbol or normalized_exchange not in TARGET_EXCHANGES:
            continue
        records.append(
            {
                "symbol": symbol,
                "exchange": normalized_exchange,
                "name": company_name,
                "cik": str(cik).strip(),
            }
        )

    records.sort(key=lambda r: (r["exchange"], r["symbol"]))
    return records


def write_master_list(records: list[dict[str, str]], output_dir: str = DEFAULT_OUTPUT_DIR) -> MasterListResult:
    started_at = perf_counter()
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    csv_path = output_path / DEFAULT_CSV_NAME
    ticker_path = output_path / DEFAULT_TICKER_NAME

    exchange_counts: dict[str, int] = {"NASDAQ": 0, "NYSE": 0}
    for record in records:
        exchange_counts[record["exchange"]] = exchange_counts.get(record["exchange"], 0) + 1

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "exchange", "name", "cik"])
        writer.writeheader()
        writer.writerows(records)

    with ticker_path.open("w", encoding="utf-8", newline="") as fh:
        for record in records:
            fh.write(record["symbol"] + "\n")

    return MasterListResult(
        output_dir=str(output_path),
        csv_path=str(csv_path),
        ticker_path=str(ticker_path),
        total_listings=sum(exchange_counts.values()),
        kept_listings=len(records),
        exchange_counts=exchange_counts,
        runtime_seconds=perf_counter() - started_at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a master Nasdaq + NYSE ticker list from the SEC exchange map")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Directory for the output files (default: {DEFAULT_OUTPUT_DIR})")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    records = fetch_master_list()
    result = write_master_list(records, output_dir=args.output_dir)

    print("Master exchange list complete")
    print(f"- Output dir: {result.output_dir}")
    print(f"- Nasdaq listings: {result.exchange_counts.get('NASDAQ', 0)}")
    print(f"- NYSE listings: {result.exchange_counts.get('NYSE', 0)}")
    print(f"- Total listings: {result.kept_listings}")
    print(f"- CSV: {result.csv_path}")
    print(f"- Ticker list: {result.ticker_path}")
    print(f"- Runtime: {result.runtime_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
