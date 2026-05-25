import csv
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import full_market_pipeline as pipeline


class FullMarketPipelineTests(unittest.TestCase):
    def test_run_full_pipeline_chains_census_filters_split_and_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            universe_file = os.path.join(tmpdir, "universe.txt")
            with open(universe_file, "w", encoding="utf-8") as fh:
                fh.write("AAA\nBBB\n")

            raw_csv_rows = [
                {
                    "rank": "1",
                    "symbol": "AAA",
                    "exchange": "NYSE",
                    "sector": "Tech",
                    "industry": "Software",
                    "price": "25.0",
                    "previous_close": "24.9",
                    "share_volume": "2000000",
                    "average_volume": "1500000",
                    "market_cap": "2000000000",
                },
                {
                    "rank": "2",
                    "symbol": "BBB",
                    "exchange": "NASDAQ-GS",
                    "sector": "Tech",
                    "industry": "Software",
                    "price": "35.0",
                    "previous_close": "34.9",
                    "share_volume": "1000000",
                    "average_volume": "1500000",
                    "market_cap": "3000000000",
                },
                {
                    "rank": "3",
                    "symbol": "CCC",
                    "exchange": "NYSE",
                    "sector": "Tech",
                    "industry": "Software",
                    "price": "9.0",
                    "previous_close": "9.0",
                    "share_volume": "2000000",
                    "average_volume": "1500000",
                    "market_cap": "4000000000",
                },
            ]

            class FakeScanner:
                def __init__(self, min_market_cap, workers):
                    self.min_market_cap = min_market_cap
                    self.workers = workers

                def load_universe(self, *, all_us=False, universe_path=None):
                    self.loaded_all_us = all_us
                    self.loaded_universe_path = universe_path
                    return ["AAA", "BBB"], universe_path or "universe.txt"

                def run(self, symbols, *, csv_path, universe_label, show_progress=True):
                    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=list(raw_csv_rows[0].keys()))
                        writer.writeheader()
                        writer.writerows(raw_csv_rows)
                    return SimpleNamespace(
                        universe_label=universe_label,
                        tickers_scanned=len(symbols),
                        survivors=raw_csv_rows,
                        csv_path=csv_path,
                        runtime_seconds=0.01,
                    )

            captured = {}

            def fake_run_exchange_workflow(input_dir, output_dir, *, mode, required_fields, workers, retry_workers, logger=None):
                captured["input_dir"] = input_dir
                captured["output_dir"] = output_dir
                captured["mode"] = mode
                captured["required_fields"] = required_fields
                captured["workers"] = workers
                captured["retry_workers"] = retry_workers
                os.makedirs(output_dir, exist_ok=True)
                with open(os.path.join(output_dir, "enrichment_report.csv"), "w", encoding="utf-8") as fh:
                    fh.write("phase,input_csv_path,output_csv_path,input_rows,output_rows,missing_rows,repaired_rows,unresolved_rows,runtime_seconds\n")
                return SimpleNamespace(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    mode=mode,
                    enriched_files=[os.path.join(output_dir, "NYSE_enriched.csv")],
                    repaired_files=[os.path.join(output_dir, "NYSE_repaired.csv")],
                    report_csv_path=os.path.join(output_dir, "enrichment_report.csv"),
                    retry_queue_csv_path=os.path.join(output_dir, "retry_queue.csv"),
                    unresolved_csv_path=os.path.join(output_dir, "unresolved.csv"),
                    runtime_seconds=0.02,
                )

            with patch.object(pipeline.census, "MarketCapCensusScanner", FakeScanner), \
                 patch.object(pipeline.enrich_workflow, "run_exchange_workflow", side_effect=fake_run_exchange_workflow):
                result = pipeline.run_full_pipeline(
                    all_us=False,
                    universe_path=universe_file,
                    workdir=tmpdir,
                    show_progress=False,
                    enrich_workers=1,
                    retry_workers=1,
                )

            self.assertEqual(result.tickers_scanned, 2)
            self.assertEqual(result.raw_survivors, 3)
            self.assertEqual(result.volume_survivors, 2)
            self.assertTrue(os.path.exists(result.raw_csv))
            self.assertTrue(os.path.exists(result.price_csv))
            self.assertTrue(os.path.exists(result.volume_csv))
            self.assertTrue(os.path.isdir(result.exchange_split_dir))
            self.assertTrue(os.path.isdir(result.enrichment_output_dir))
            self.assertEqual(captured["mode"], "full")
            self.assertEqual(captured["workers"], 1)
            self.assertEqual(captured["retry_workers"], 1)
            self.assertIn("price", captured["required_fields"])
            self.assertIn("open_interest", captured["required_fields"])

            with open(result.volume_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["AAA", "BBB"])


if __name__ == "__main__":
    unittest.main()
