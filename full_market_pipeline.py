#!/usr/bin/env python3
"""One-command end-to-end market funnel workflow.

Flow:
1. Run the raw market-cap census from either the SEC universe or a local universe file
2. Apply price + volume rough filters
3. Split the survivors by exchange
4. Enrich each exchange separately
5. Verify/retry rows with missing premium fields

This keeps exchange splitting as a workflow convenience, not a trading filter.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Optional, Tuple

import exchange_enrichment_workflow as enrich_workflow
import market_cap_census as census
from pipeline_logging import configure_logging, log_event

DEFAULT_WORKDIR = "/tmp/market_funnel_full_pipeline"
DEFAULT_PRICE_MIN = 10.0
DEFAULT_PRICE_MAX = 75.0
DEFAULT_VOLUME_MIN = 1_000_000
DEFAULT_MIN_MARKET_CAP = 1e9
DEFAULT_REQUIRED_FIELDS = "price,market_cap,implied_volatility,options_volume,open_interest,atm_bid_ask_spread"


@dataclass
class PipelineResult:
    universe_label: str
    tickers_scanned: int
    raw_csv: str
    price_csv: str
    volume_csv: str
    exchange_split_dir: str
    enrichment_output_dir: str
    raw_survivors: int
    volume_survivors: int
    runtime_seconds: float


def _parse_required_fields(required_fields: Optional[str]) -> Tuple[str, ...]:
    if not required_fields:
        return enrich_workflow.DEFAULT_REQUIRED_FIELDS
    fields = [part.strip() for part in required_fields.split(",") if part.strip()]
    return tuple(dict.fromkeys(fields))


def _filter_price_volume(
    input_csv: str,
    price_csv: str,
    volume_csv: str,
    *,
    min_price: float,
    max_price: float,
    min_volume: float,
) -> Tuple[census.PriceFilterRunResult, census.VolumeFilterRunResult]:
    price_filter = census.CensusCSVPriceFilter(min_price=min_price, max_price=max_price)
    volume_filter = census.CensusCSVVolumeFilter(min_volume=min_volume)
    price_result = price_filter.run(input_csv, price_csv)
    volume_result = volume_filter.run(price_csv, volume_csv)
    return price_result, volume_result


def run_full_pipeline(
    *,
    all_us: bool = False,
    universe_path: Optional[str] = None,
    workdir: str = DEFAULT_WORKDIR,
    min_price: float = DEFAULT_PRICE_MIN,
    max_price: float = DEFAULT_PRICE_MAX,
    min_volume: float = DEFAULT_VOLUME_MIN,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    census_workers: int = 4,
    enrich_workers: int = 3,
    retry_workers: int = 1,
    required_fields: str = DEFAULT_REQUIRED_FIELDS,
    show_progress: bool = True,
    logger=None,
) -> PipelineResult:
    started_at = perf_counter()
    workdir_path = Path(workdir).expanduser()
    workdir_path.mkdir(parents=True, exist_ok=True)

    raw_csv = str(workdir_path / "market_cap_census.csv")
    price_csv = str(workdir_path / "market_cap_census_10_to_75.csv")
    volume_csv = str(workdir_path / "market_cap_census_10_to_75_volume_1m.csv")
    exchange_split_dir = str(workdir_path / "exchange_splits")
    enrichment_output_dir = str(workdir_path / "exchange_enrichment")

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_start",
            all_us=all_us,
            universe_path=universe_path,
            workdir=str(workdir_path),
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            min_market_cap=min_market_cap,
            census_workers=census_workers,
            enrich_workers=enrich_workers,
            retry_workers=retry_workers,
        )

    scanner = census.MarketCapCensusScanner(min_market_cap=min_market_cap, workers=census_workers)
    symbols, universe_label = scanner.load_universe(all_us=all_us, universe_path=universe_path)
    census_result = scanner.run(symbols, csv_path=raw_csv, universe_label=universe_label, show_progress=show_progress)

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_census_complete",
            universe_label=universe_label,
            tickers_scanned=census_result.tickers_scanned,
            raw_survivors=len(census_result.survivors),
            raw_csv=raw_csv,
            runtime_seconds=round(census_result.runtime_seconds, 4),
        )

    price_result, volume_result = _filter_price_volume(
        raw_csv,
        price_csv,
        volume_csv,
        min_price=min_price,
        max_price=max_price,
        min_volume=min_volume,
    )

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_filters_complete",
            price_input_rows=price_result.input_rows,
            price_output_rows=price_result.filtered_rows,
            volume_input_rows=volume_result.input_rows,
            volume_output_rows=volume_result.filtered_rows,
            price_csv=price_csv,
            volume_csv=volume_csv,
            price_runtime_seconds=round(price_result.runtime_seconds, 4),
            volume_runtime_seconds=round(volume_result.runtime_seconds, 4),
        )

    exchange_split_result = census.split_census_csv_by_exchange(volume_csv, exchange_split_dir)

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_exchange_split_complete",
            input_rows=exchange_split_result.input_rows,
            exchange_files=len(exchange_split_result.exchange_files),
            output_dir=exchange_split_dir,
            runtime_seconds=round(exchange_split_result.runtime_seconds, 4),
        )

    enrich_result = enrich_workflow.run_exchange_workflow(
        exchange_split_dir,
        enrichment_output_dir,
        mode="full",
        required_fields=_parse_required_fields(required_fields),
        workers=enrich_workers,
        retry_workers=retry_workers,
        logger=logger,
    )

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_enrichment_complete",
            enriched_files=len(enrich_result.enriched_files),
            repaired_files=len(enrich_result.repaired_files),
            report_csv_path=enrich_result.report_csv_path,
            retry_queue_csv_path=enrich_result.retry_queue_csv_path,
            unresolved_csv_path=enrich_result.unresolved_csv_path,
            runtime_seconds=round(enrich_result.runtime_seconds, 4),
        )

    result = PipelineResult(
        universe_label=census_result.universe_label,
        tickers_scanned=census_result.tickers_scanned,
        raw_csv=raw_csv,
        price_csv=price_csv,
        volume_csv=volume_csv,
        exchange_split_dir=exchange_split_dir,
        enrichment_output_dir=enrichment_output_dir,
        raw_survivors=len(census_result.survivors),
        volume_survivors=volume_result.filtered_rows,
        runtime_seconds=perf_counter() - started_at,
    )

    if logger is not None:
        log_event(
            logger,
            "full_pipeline_complete",
            universe_label=result.universe_label,
            tickers_scanned=result.tickers_scanned,
            raw_survivors=result.raw_survivors,
            volume_survivors=result.volume_survivors,
            runtime_seconds=round(result.runtime_seconds, 4),
            workdir=str(workdir_path),
        )

    return result



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="End-to-end market funnel workflow")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--all-us", action="store_true", help="Scan the SEC company ticker map")
    src.add_argument("--universe", help="Text file with tickers to scan")
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR, help=f"Working directory for all generated artifacts (default: {DEFAULT_WORKDIR})")
    parser.add_argument("--min-price", type=float, default=DEFAULT_PRICE_MIN)
    parser.add_argument("--max-price", type=float, default=DEFAULT_PRICE_MAX)
    parser.add_argument("--min-volume", type=float, default=DEFAULT_VOLUME_MIN)
    parser.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP)
    parser.add_argument("--required-fields", default=DEFAULT_REQUIRED_FIELDS)
    parser.add_argument("--census-workers", type=int, default=4)
    parser.add_argument("--enrich-workers", type=int, default=3)
    parser.add_argument("--retry-workers", type=int, default=1)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-file")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = configure_logging(level=args.log_level, log_file=args.log_file)

    result = run_full_pipeline(
        all_us=args.all_us,
        universe_path=args.universe,
        workdir=args.workdir,
        min_price=args.min_price,
        max_price=args.max_price,
        min_volume=args.min_volume,
        min_market_cap=args.min_market_cap,
        census_workers=args.census_workers,
        enrich_workers=args.enrich_workers,
        retry_workers=args.retry_workers,
        required_fields=args.required_fields,
        logger=logger,
    )

    print("End-to-end pipeline complete")
    print(f"- Universe: {result.universe_label}")
    print(f"- Tickers scanned: {result.tickers_scanned}")
    print(f"- Raw census CSV: {result.raw_csv}")
    print(f"- Raw survivors: {result.raw_survivors}")
    print(f"- Price-filtered CSV: {result.price_csv}")
    print(f"- Volume-filtered CSV: {result.volume_csv}")
    print(f"- Volume survivors: {result.volume_survivors}")
    print(f"- Exchange splits: {result.exchange_split_dir}")
    print(f"- Enrichment output: {result.enrichment_output_dir}")
    print(f"- Runtime: {result.runtime_seconds:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
