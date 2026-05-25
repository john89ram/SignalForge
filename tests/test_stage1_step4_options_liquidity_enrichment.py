import csv
import json
import os
import tempfile
import unittest

from screener import OptionsSnapshot
from stages.stage1.code.step4_options_liquidity_enrichment import run_stage1_step4_options_liquidity_enrichment


class Stage1Step4OptionsLiquidityEnrichmentTests(unittest.TestCase):
    def _write_barchart_csv(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fieldnames = ["symbol", "master_exchange", "price_proxy", "barchart_implied_volatility"]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_cache_csv(self, path):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["symbol", "options_volume", "open_interest", "atm_bid_ask_spread"])
            writer.writeheader()
            writer.writerow({"symbol": "AAA", "options_volume": "5000", "open_interest": "4000", "atm_bid_ask_spread": "0.2"})

    def test_merges_cache_and_live_liquidity_logs_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "barchart")
            output_csv = os.path.join(tmpdir, "output", "stage1_step4_options_liquidity_enriched.csv")
            audit_log = os.path.join(tmpdir, "audit", "step4.jsonl")
            cache_csv = os.path.join(tmpdir, "cache.csv")
            self._write_cache_csv(cache_csv)
            self._write_barchart_csv(os.path.join(input_dir, "NASDAQ_barchart_enriched.csv"), [
                {"symbol": "AAA", "master_exchange": "NASDAQ", "price_proxy": "25", "barchart_implied_volatility": "80"},
            ])
            self._write_barchart_csv(os.path.join(input_dir, "NYSE_barchart_enriched.csv"), [
                {"symbol": "BBB", "master_exchange": "NYSE", "price_proxy": "30", "barchart_implied_volatility": "90"},
            ])

            def fake_fetcher(symbol, price):
                self.assertEqual(symbol, "BBB")
                self.assertEqual(price, 30.0)
                return OptionsSnapshot(total_volume=1200, total_open_interest=1500, atm_bid_ask_spread=0.4), ""

            result = run_stage1_step4_options_liquidity_enrichment(
                input_dir=input_dir,
                output_csv_path=output_csv,
                audit_log_path=audit_log,
                liquidity_cache_csvs=(cache_csv,),
                delay_seconds=0,
                fetcher=fake_fetcher,
                show_progress=False,
            )

            self.assertEqual(result.total_input_rows, 2)
            self.assertEqual(result.cache_hit_rows, 1)
            self.assertEqual(result.fetched_rows, 1)
            self.assertEqual(result.missing_rows, 0)
            with open(output_csv, "r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["AAA", "BBB"])
            self.assertEqual(rows[0]["options_liquidity_source"], "cache")
            self.assertEqual(rows[1]["options_volume"], "1200")
            with open(audit_log, "r", encoding="utf-8") as fh:
                event = json.loads(fh.read().strip())
            self.assertEqual(event["event"], "stage1_step4_options_liquidity_enrichment_complete")
            self.assertEqual(event["cache_hit_rows"], 1)


if __name__ == "__main__":
    unittest.main()
