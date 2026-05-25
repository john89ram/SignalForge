#!/usr/bin/env python3
"""Lightweight U.S. market-cap census scanner.

Purpose:
- pull a broad U.S.-listed universe
- check live market cap only
- keep names with market cap >= threshold
- export the raw survivor list to CSV

This is still market-cap first, but it also carries forward a few
trading-relevant fields so the downstream shrink steps already have the
columns they need.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable, List, Optional, Tuple

from screener import HTTP, load_all_us_tickers, parse_barchart_overview, parse_finviz_options


NASDAQ_SUMMARY_URL = "https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks"
DEFAULT_MIN_MARKET_CAP = 1e9
DEFAULT_WORKERS = 12
DEFAULT_CSV_PATH = "/tmp/market_cap_census.csv"


@dataclass
class CensusRow:
    symbol: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    price: Optional[float] = None
    previous_close: Optional[float] = None
    share_volume: Optional[float] = None
    stock_volume_today: Optional[float] = None
    average_volume: Optional[float] = None
    implied_volatility: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    historical_volatility: Optional[float] = None
    expected_move: Optional[float] = None
    options_volume: Optional[int] = None
    open_interest: Optional[int] = None
    atm_bid_ask_spread: Optional[float] = None
    market_cap: Optional[float] = None


@dataclass
class CensusRunResult:
    universe_label: str
    tickers_scanned: int
    survivors: List[CensusRow]
    csv_path: str
    runtime_seconds: float



def _parse_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("$", "").strip()
    if not text or text in {"-", "N/A", "NA"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None



def _parse_money(value: Optional[str]) -> Optional[float]:
    return _parse_number(value)



def _normalize_symbols(symbols: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(sym.upper().strip() for sym in symbols if sym and sym.strip()))



def fetch_census_row(
    symbol: str,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    http: Optional[HTTP] = None,
) -> Optional[CensusRow]:
    http = http or HTTP()
    symbol = symbol.upper().strip()

    try:
        payload = http.get(
            NASDAQ_SUMMARY_URL.format(symbol=symbol),
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nasdaq.com/",
            },
        ).json()
    except Exception:
        return None

    data = payload.get("data") or {}
    summary = data.get("summaryData") or {}
    market_cap = _parse_money((summary.get("MarketCap") or {}).get("value") if isinstance(summary.get("MarketCap"), dict) else summary.get("MarketCap"))
    if market_cap is None or market_cap < min_market_cap:
        return None

    today_high_low = summary.get("TodayHighLow") or {}
    previous_close = _parse_money((summary.get("PreviousClose") or {}).get("value") if isinstance(summary.get("PreviousClose"), dict) else summary.get("PreviousClose"))
    if previous_close is None and isinstance(today_high_low, dict):
        hl_value = today_high_low.get("value")
        if isinstance(hl_value, str) and "/" in hl_value:
            previous_close = _parse_number(hl_value.split("/")[0])

    share_volume = _parse_number((summary.get("ShareVolume") or {}).get("value") if isinstance(summary.get("ShareVolume"), dict) else summary.get("ShareVolume"))
    average_volume = _parse_number((summary.get("AverageVolume") or {}).get("value") if isinstance(summary.get("AverageVolume"), dict) else summary.get("AverageVolume"))

    price = previous_close
    if isinstance(today_high_low, dict):
        hl_value = today_high_low.get("value")
        if isinstance(hl_value, str) and "/" in hl_value:
            price = _parse_number(hl_value.split("/")[0]) or price

    implied_volatility = None
    iv_rank = None
    iv_percentile = None
    historical_volatility = None
    expected_move = None
    options_volume = None
    open_interest = None
    atm_bid_ask_spread = None

    try:
        barchart = parse_barchart_overview(http.get(f"https://www.barchart.com/stocks/quotes/{symbol}/overview").text)
        implied_volatility = barchart.implied_volatility
        iv_rank = barchart.iv_rank
        iv_percentile = barchart.iv_percentile
        historical_volatility = barchart.historical_volatility
        expected_move = barchart.expected_move
    except Exception:
        pass

    try:
        options = parse_finviz_options(http.get(f"https://finviz.com/quote.ashx?t={symbol}&ta=1&p=d&ty=oc").text, price)
        options_volume = options.total_volume
        open_interest = options.total_open_interest
        atm_bid_ask_spread = options.atm_bid_ask_spread
    except Exception:
        pass

    return CensusRow(
        symbol=symbol,
        exchange=(summary.get("Exchange") or {}).get("value") if isinstance(summary.get("Exchange"), dict) else summary.get("Exchange"),
        sector=(summary.get("Sector") or {}).get("value") if isinstance(summary.get("Sector"), dict) else summary.get("Sector"),
        industry=(summary.get("Industry") or {}).get("value") if isinstance(summary.get("Industry"), dict) else summary.get("Industry"),
        price=price,
        previous_close=previous_close,
        share_volume=share_volume,
        stock_volume_today=share_volume,
        average_volume=average_volume,
        implied_volatility=implied_volatility,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        historical_volatility=historical_volatility,
        expected_move=expected_move,
        options_volume=options_volume,
        open_interest=open_interest,
        atm_bid_ask_spread=atm_bid_ask_spread,
        market_cap=market_cap,
    )


@dataclass
class MarketCapCensusScanner:
    http: Optional[HTTP] = None
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP
    workers: int = DEFAULT_WORKERS
    fetch_row: Optional[Callable[..., Optional[CensusRow]]] = None

    def __post_init__(self) -> None:
        if self.fetch_row is None:
            self.fetch_row = fetch_census_row

    def _get_http(self) -> HTTP:
        if self.http is None:
            self.http = HTTP()
        return self.http

    def load_universe(self, *, all_us: bool = False, universe_path: Optional[str] = None) -> Tuple[List[str], str]:
        if all_us:
            return load_all_us_tickers(self._get_http()), "SEC company ticker map"
        if universe_path:
            return load_tickers_from_file(universe_path), universe_path
        raise ValueError("Provide all_us=True or universe_path=<file>")

    def scan(self, symbols: Iterable[str], *, show_progress: bool = True) -> List[CensusRow]:
        symbols = list(dict.fromkeys(sym.upper().strip() for sym in symbols if sym and sym.strip()))
        if not symbols:
            return []

        def _fetch(sym: str) -> Optional[CensusRow]:
            try:
                return self.fetch_row(sym, min_market_cap=self.min_market_cap, http=self.http)
            except Exception:
                return None

        started_at = perf_counter()
        rows: List[Optional[CensusRow]] = []
        total = len(symbols)
        completed = 0
        last_render_completed = 0
        last_render_at = started_at
        update_every = max(1, total // 200)

        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as executor:
            futures = [executor.submit(_fetch, sym) for sym in symbols]
            for future in futures:
                rows.append(future.result())
                completed += 1

                if show_progress:
                    now = perf_counter()
                    should_render = (
                        completed == total
                        or completed - last_render_completed >= update_every
                        or (now - last_render_at) >= 1.0
                    )
                    if should_render:
                        _emit_progress_bar(completed, total, started_at=started_at, final=completed == total)
                        last_render_completed = completed
                        last_render_at = now

        survivors = [row for row in rows if row is not None]
        survivors.sort(key=lambda r: (-(r.market_cap or 0), r.symbol))
        return survivors

    def run(
        self,
        symbols: Iterable[str],
        *,
        csv_path: str = DEFAULT_CSV_PATH,
        universe_label: str = "",
        show_progress: bool = True,
    ) -> CensusRunResult:
        normalized_symbols = _normalize_symbols(symbols)
        started_at = perf_counter()
        survivors = self.scan(normalized_symbols, show_progress=show_progress)
        write_csv(survivors, csv_path)
        runtime_seconds = perf_counter() - started_at
        return CensusRunResult(
            universe_label=universe_label,
            tickers_scanned=len(normalized_symbols),
            survivors=survivors,
            csv_path=csv_path,
            runtime_seconds=runtime_seconds,
        )



def write_csv(rows: List[CensusRow], path: str) -> None:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "rank",
            "symbol",
            "exchange",
            "sector",
            "industry",
            "price",
            "previous_close",
            "stock_volume_today",
            "share_volume",
            "average_volume",
            "implied_volatility",
            "iv_rank",
            "iv_percentile",
            "historical_volatility",
            "expected_move",
            "options_volume",
            "open_interest",
            "atm_bid_ask_spread",
            "market_cap",
        ])
        for idx, row in enumerate(rows, start=1):
            writer.writerow([
                idx,
                row.symbol,
                row.exchange or "",
                row.sector or "",
                row.industry or "",
                row.price if row.price is not None else "",
                row.previous_close if row.previous_close is not None else "",
                row.stock_volume_today if row.stock_volume_today is not None else "",
                row.share_volume if row.share_volume is not None else "",
                row.average_volume if row.average_volume is not None else "",
                row.implied_volatility if row.implied_volatility is not None else "",
                row.iv_rank if row.iv_rank is not None else "",
                row.iv_percentile if row.iv_percentile is not None else "",
                row.historical_volatility if row.historical_volatility is not None else "",
                row.expected_move if row.expected_move is not None else "",
                row.options_volume if row.options_volume is not None else "",
                row.open_interest if row.open_interest is not None else "",
                row.atm_bid_ask_spread if row.atm_bid_ask_spread is not None else "",
                row.market_cap if row.market_cap is not None else "",
            ])



@dataclass
class PriceFilterRunResult:
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    filtered_rows: int
    runtime_seconds: float


@dataclass
class VolumeFilterRunResult:
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    filtered_rows: int
    runtime_seconds: float


@dataclass
class OpenInterestFilterRunResult:
    input_csv_path: str
    output_csv_path: str
    input_rows: int
    filtered_rows: int
    runtime_seconds: float


@dataclass
class CensusShrinkPipelineResult:
    input_csv_path: str
    price_csv_path: str
    volume_csv_path: str
    open_interest_csv_path: str
    final_csv_path: str
    input_rows: int
    price_result: PriceFilterRunResult
    volume_result: VolumeFilterRunResult
    open_interest_result: OpenInterestFilterRunResult
    runtime_seconds: float


def _shrink_output_paths(input_csv_path: str) -> Tuple[str, str, str]:
    source = Path(input_csv_path).expanduser()
    base = source.with_suffix("")
    price_csv_path = f"{base}_10_to_75.csv"
    volume_csv_path = f"{base}_10_to_75_volume_1m.csv"
    open_interest_csv_path = f"{base}_10_to_75_volume_1m_oi1k.csv"
    return price_csv_path, volume_csv_path, open_interest_csv_path


def run_census_shrink_pipeline(
    input_csv_path: str,
    *,
    price_csv_path: Optional[str] = None,
    volume_csv_path: Optional[str] = None,
    open_interest_csv_path: Optional[str] = None,
    min_price: float = 10.0,
    max_price: float = 75.0,
    min_volume: float = 1_000_000,
    min_open_interest: float = 1_000,
    emit_progress: bool = True,
) -> CensusShrinkPipelineResult:
    started_at = perf_counter()
    default_price_csv_path, default_volume_csv_path, default_open_interest_csv_path = _shrink_output_paths(input_csv_path)
    price_csv_path = price_csv_path or default_price_csv_path
    volume_csv_path = volume_csv_path or default_volume_csv_path
    open_interest_csv_path = open_interest_csv_path or default_open_interest_csv_path

    if emit_progress:
        print(f"Starting shrink pipeline: {input_csv_path}")
        print(f"- Price filter: ${min_price:,.2f} to ${max_price:,.2f}")
        print(f"- Volume filter: >= {min_volume:,.0f}")
        print(f"- Open interest filter: >= {min_open_interest:,.0f}")

    with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
        input_rows = list(csv.DictReader(fh))
    input_count = len(input_rows)

    price_filter = CensusCSVPriceFilter(min_price=min_price, max_price=max_price)
    price_result = price_filter.run(input_csv_path, price_csv_path)
    if emit_progress:
        print(
            f"After price filter: {price_result.filtered_rows}/{price_result.input_rows} rows kept "
            f"({format_runtime(price_result.runtime_seconds)}) -> {price_result.output_csv_path}"
        )

    volume_filter = CensusCSVVolumeFilter(min_volume=min_volume)
    volume_result = volume_filter.run(price_csv_path, volume_csv_path)
    if emit_progress:
        print(
            f"After volume filter: {volume_result.filtered_rows}/{volume_result.input_rows} rows kept "
            f"({format_runtime(volume_result.runtime_seconds)}) -> {volume_result.output_csv_path}"
        )

    open_interest_filter = CensusCSVOpenInterestFilter(min_open_interest=min_open_interest)
    open_interest_result = open_interest_filter.run(volume_csv_path, open_interest_csv_path)
    if emit_progress:
        print(
            f"After open-interest filter: {open_interest_result.filtered_rows}/{open_interest_result.input_rows} rows kept "
            f"({format_runtime(open_interest_result.runtime_seconds)}) -> {open_interest_result.output_csv_path}"
        )
        print(f"Pipeline complete: {open_interest_result.filtered_rows} survivors")
        print(f"Runtime: {format_runtime(perf_counter() - started_at)}")
        print(f"Total runtime: {format_runtime(perf_counter() - started_at)}")

    return CensusShrinkPipelineResult(
        input_csv_path=input_csv_path,
        price_csv_path=price_csv_path,
        volume_csv_path=volume_csv_path,
        open_interest_csv_path=open_interest_csv_path,
        final_csv_path=open_interest_csv_path,
        input_rows=input_count,
        price_result=price_result,
        volume_result=volume_result,
        open_interest_result=open_interest_result,
        runtime_seconds=perf_counter() - started_at,
    )



@dataclass
class CensusCSVPriceFilter:
    min_price: float = 10.0
    max_price: float = 75.0

    def _price_in_range(self, value: Optional[str]) -> bool:
        price = _parse_number(value)
        if price is None:
            return False
        return self.min_price <= price <= self.max_price

    def filter_rows(self, input_csv_path: str) -> List[dict]:
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return [row for row in rows if self._price_in_range(row.get("price"))]

    def run(self, input_csv_path: str, output_csv_path: str) -> PriceFilterRunResult:
        started_at = perf_counter()
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

        filtered_rows = [row for row in rows if self._price_in_range(row.get("price"))]

        output_path = Path(output_csv_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            if rows:
                fieldnames = list(rows[0].keys())
            else:
                fieldnames = []
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if fieldnames:
                writer.writeheader()
                writer.writerows(filtered_rows)

        return PriceFilterRunResult(
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=len(rows),
            filtered_rows=len(filtered_rows),
            runtime_seconds=perf_counter() - started_at,
        )


@dataclass
class CensusCSVVolumeFilter:
    min_volume: float = 1_000_000

    def _volume_in_range(self, value: Optional[str]) -> bool:
        volume = _parse_number(value)
        if volume is None:
            return False
        return volume >= self.min_volume

    def filter_rows(self, input_csv_path: str) -> List[dict]:
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return [row for row in rows if self._volume_in_range(row.get("share_volume"))]

    def run(self, input_csv_path: str, output_csv_path: str) -> VolumeFilterRunResult:
        started_at = perf_counter()
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

        filtered_rows = [row for row in rows if self._volume_in_range(row.get("share_volume"))]

        output_path = Path(output_csv_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            if rows:
                fieldnames = list(rows[0].keys())
            else:
                fieldnames = []
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if fieldnames:
                writer.writeheader()
                writer.writerows(filtered_rows)

        return VolumeFilterRunResult(
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=len(rows),
            filtered_rows=len(filtered_rows),
            runtime_seconds=perf_counter() - started_at,
        )


@dataclass
class CensusCSVOpenInterestFilter:
    min_open_interest: float = 1_000

    def _open_interest_in_range(self, value: Optional[str]) -> bool:
        open_interest = _parse_number(value)
        if open_interest is None:
            return False
        return open_interest >= self.min_open_interest

    def filter_rows(self, input_csv_path: str) -> List[dict]:
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return [row for row in rows if self._open_interest_in_range(row.get("open_interest"))]

    def run(self, input_csv_path: str, output_csv_path: str) -> OpenInterestFilterRunResult:
        started_at = perf_counter()
        with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

        filtered_rows = [row for row in rows if self._open_interest_in_range(row.get("open_interest"))]

        output_path = Path(output_csv_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as fh:
            if rows:
                fieldnames = list(rows[0].keys())
            else:
                fieldnames = []
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if fieldnames:
                writer.writeheader()
                writer.writerows(filtered_rows)

        return OpenInterestFilterRunResult(
            input_csv_path=input_csv_path,
            output_csv_path=output_csv_path,
            input_rows=len(rows),
            filtered_rows=len(filtered_rows),
            runtime_seconds=perf_counter() - started_at,
        )


@dataclass
class ExchangeSplitRunResult:
    input_csv_path: str
    output_dir: str
    input_rows: int
    exchange_files: dict[str, str]
    runtime_seconds: float


def _normalize_exchange_name(exchange: Optional[str]) -> str:
    value = (exchange or "").strip()
    return value if value else "UNKNOWN"


def _exchange_output_filename(exchange: str) -> str:
    if exchange == "AMEX":
        return "AMEX Exchange.csv"
    safe = exchange.replace("/", "-").replace(" ", "_").strip()
    return f"{safe or 'UNKNOWN'}.csv"


def split_census_csv_by_exchange(
    input_csv_path: str,
    output_dir: str,
) -> ExchangeSplitRunResult:
    started_at = perf_counter()
    with open(input_csv_path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    fieldnames = list(rows[0].keys()) if rows else []
    grouped_rows: dict[str, list[dict]] = {}
    for row in rows:
        exchange = _normalize_exchange_name(row.get("exchange"))
        grouped_rows.setdefault(exchange, []).append(row)

    desired_order = ["AMEX", "NASDAQ-GM", "NASDAQ-CM", "NASDAQ-GS", "NYSE"]
    seen = set()
    exchange_files: dict[str, str] = {}
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    def _write_group(exchange: str, exchange_rows: list[dict]) -> None:
        filename = _exchange_output_filename(exchange)
        target_path = output_path / filename
        with target_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if fieldnames:
                writer.writeheader()
                writer.writerows(exchange_rows)
        exchange_files[exchange] = str(target_path)

    for exchange in desired_order:
        seen.add(exchange)
        _write_group(exchange, grouped_rows.get(exchange, []))

    for exchange in sorted(grouped_rows):
        if exchange in seen:
            continue
        _write_group(exchange, grouped_rows[exchange])

    return ExchangeSplitRunResult(
        input_csv_path=input_csv_path,
        output_dir=str(output_path),
        input_rows=len(rows),
        exchange_files=exchange_files,
        runtime_seconds=perf_counter() - started_at,
    )



def format_runtime(seconds: float) -> str:
    total_seconds = max(0.0, float(seconds))
    minutes, remainder = divmod(total_seconds, 60.0)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remainder:05.2f}s"
    if minutes:
        return f"{minutes}m {remainder:05.2f}s"
    return f"{remainder:.2f}s"


def _render_progress_bar(completed: int, total: int, *, started_at: float, width: int = 28) -> str:
    if total <= 0:
        return "Progress: [----------------------------] 0/0"

    fraction = min(1.0, max(0.0, completed / total))
    filled = min(width, int(round(width * fraction)))
    bar = "█" * filled + "░" * (width - filled)
    percent = int(round(100 * fraction))

    elapsed = max(0.0, perf_counter() - started_at)
    rate = (completed / elapsed) if completed and elapsed > 0 else 0.0
    eta = ((total - completed) / rate) if rate > 0 and completed < total else None
    rate_text = f"{rate:.1f}/s" if rate > 0 else "--/s"
    eta_text = f" ETA {format_runtime(eta)}" if eta is not None else ""
    return f"Progress: [{bar}] {completed}/{total} ({percent}%) {rate_text}{eta_text}"


def _emit_progress_bar(completed: int, total: int, *, started_at: float, final: bool = False) -> None:
    line = _render_progress_bar(completed, total, started_at=started_at)
    sys.stdout.write(line + ("\n" if final else "\r"))
    sys.stdout.flush()


def print_run_summary(result: CensusRunResult) -> None:
    if result.universe_label:
        print(f"Universe source: {result.universe_label}")
    print(f"Tickers scanned: {result.tickers_scanned}")
    print(f"Market cap >= ${DEFAULT_MIN_MARKET_CAP:,.0f} survivors: {len(result.survivors)}")
    print(f"CSV written: {result.csv_path}")
    print(f"Runtime: {format_runtime(result.runtime_seconds)}")


def print_exchange_split_summary(result: ExchangeSplitRunResult) -> None:
    print(f"Input CSV: {result.input_csv_path}")
    print(f"Rows read: {result.input_rows}")
    print(f"Output dir: {result.output_dir}")
    print(f"Files written: {len(result.exchange_files)}")
    for exchange, path in result.exchange_files.items():
        print(f"- {exchange}: {path}")
    print(f"Runtime: {format_runtime(result.runtime_seconds)}")


def run_market_cap_census(
    symbols: Iterable[str],
    *,
    csv_path: str = DEFAULT_CSV_PATH,
    universe_label: str = "",
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    workers: int = DEFAULT_WORKERS,
    http: Optional[HTTP] = None,
    fetch_row: Optional[Callable[..., Optional[CensusRow]]] = None,
    show_progress: bool = True,
) -> CensusRunResult:
    scanner = MarketCapCensusScanner(
        http=http,
        min_market_cap=min_market_cap,
        workers=workers,
        fetch_row=fetch_row,
    )
    normalized_symbols = _normalize_symbols(symbols)
    result = scanner.run(
        normalized_symbols,
        csv_path=csv_path,
        universe_label=universe_label,
        show_progress=show_progress,
    )
    return result



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lightweight market-cap census scanner")
    parser.add_argument("--all-us", action="store_true", help="Scan the SEC company ticker map")
    parser.add_argument("--universe", help="Text file with tickers, one per line or comma separated")
    parser.add_argument("--csv-path", default=DEFAULT_CSV_PATH, help=f"Write CSV output to this file path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrency for live market-cap fetches")
    parser.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP, help="Minimum market cap to keep (default: 1e9)")
    parser.add_argument("--split-by-exchange", action="store_true", help="Split an existing census CSV into per-exchange files")
    parser.add_argument("--input-csv", help="Input CSV to split by exchange")
    parser.add_argument("--output-dir", help="Directory to write exchange-split CSV files")
    return parser



def load_tickers_from_file(path: str) -> List[str]:
    tickers: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tickers.extend([part.strip().upper() for part in line.split(",") if part.strip()])
    return list(dict.fromkeys(tickers))



def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.split_by_exchange:
        if not args.input_csv:
            print("Provide --input-csv when using --split-by-exchange", file=sys.stderr)
            return 2
        if not args.output_dir:
            print("Provide --output-dir when using --split-by-exchange", file=sys.stderr)
            return 2
        result = split_census_csv_by_exchange(args.input_csv, args.output_dir)
        print_exchange_split_summary(result)
        return 0

    scanner = MarketCapCensusScanner(min_market_cap=args.min_market_cap, workers=args.workers)
    if args.all_us:
        tickers, universe_label = scanner.load_universe(all_us=True)
    elif args.universe:
        tickers, universe_label = scanner.load_universe(universe_path=args.universe)
    else:
        print("Provide --all-us or --universe", file=sys.stderr)
        return 2

    result = scanner.run(
        tickers,
        csv_path=args.csv_path,
        universe_label=universe_label,
        show_progress=True,
    )
    print_run_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
