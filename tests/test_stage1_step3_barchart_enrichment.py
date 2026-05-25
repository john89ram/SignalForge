import csv
import os
import tempfile
import unittest

from screener import BarchartSnapshot
from stages.stage1.code.step3_barchart_enrichment import (
    DEFAULT_REQUIRED_FIELDS,
    enrich_rows_with_repair,
    missing_fields,
    run_stage1_step3_barchart_enrichment,
)


class Stage1Step3BarchartEnrichmentTests(unittest.TestCase):
    def _snapshot(self, implied=80.0):
        return BarchartSnapshot(
            implied_volatility=implied,
            historical_volatility=70.0,
            iv_percentile=60.0,
            iv_rank=50.0,
            iv_high=120.0,
            iv_low=20.0,
            expected_move=5.0,
        )

    def test_missing_fields_detects_required_gaps(self):
        row = {
            "barchart_implied_volatility": "80",
            "barchart_historical_volatility": "70",
            "barchart_iv_percentile": "",
            "barchart_iv_rank": "50",
            "barchart_expected_move": "5",
        }
        self.assertEqual(missing_fields(row, DEFAULT_REQUIRED_FIELDS), ["barchart_iv_percentile"])

    def test_enrich_rows_with_repair_retries_missing_rows_only_twice(self):
        calls = {"AAA": 0, "BBB": 0}

        def fetcher(symbol):
            calls[symbol] += 1
            if symbol == "AAA":
                return self._snapshot(), ""
            if calls[symbol] < 3:
                return BarchartSnapshot(implied_volatility=None), ""
            return self._snapshot(implied=90.0), ""

        rows = [
            {"symbol": "AAA", "master_exchange": "NYSE"},
            {"symbol": "BBB", "master_exchange": "NASDAQ"},
        ]
        enriched, initial_missing, final_missing, rounds_run = enrich_rows_with_repair(
            rows,
            max_repair_rounds=2,
            delay_seconds=0,
            fetcher=fetcher,
            show_progress=False,
            exchange="TEST",
        )

        self.assertEqual(initial_missing, 1)
        self.assertEqual(final_missing, 0)
        self.assertEqual(rounds_run, 2)
        self.assertEqual(calls["AAA"], 1)
        self.assertEqual(calls["BBB"], 3)
        bbb = next(row for row in enriched if row["symbol"] == "BBB")
        self.assertEqual(bbb["barchart_fetch_round"], "2")
        self.assertEqual(bbb["barchart_missing_fields"], "")

    def test_run_stage1_step3_barchart_enrichment_writes_outputs_and_audit_log(self):
        def fetcher(symbol):
            return self._snapshot(), ""

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "splits")
            output_dir = os.path.join(tmpdir, "out")
            audit_log = os.path.join(tmpdir, "audit.jsonl")
            os.makedirs(input_dir, exist_ok=True)
            for exchange, symbol in (("NYSE", "AAA"), ("NASDAQ", "BBB")):
                with open(os.path.join(input_dir, f"{exchange}.csv"), "w", encoding="utf-8", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=["symbol", "master_exchange", "price_proxy"])
                    writer.writeheader()
                    writer.writerow({"symbol": symbol, "master_exchange": exchange, "price_proxy": "25"})

            result = run_stage1_step3_barchart_enrichment(
                input_dir=input_dir,
                output_dir=output_dir,
                audit_log_path=audit_log,
                max_repair_rounds=2,
                delay_seconds=0,
                fetcher=fetcher,
                show_progress=False,
            )

            self.assertEqual(result.total_input_rows, 2)
            self.assertEqual(result.total_enriched_rows, 2)
            self.assertEqual(result.total_final_missing_rows, 0)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NYSE_barchart_enriched.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NASDAQ_barchart_enriched.csv")))
            self.assertTrue(os.path.exists(result.retry_queue_csv_path))
            self.assertTrue(os.path.exists(result.unresolved_csv_path))
            self.assertTrue(os.path.exists(audit_log))

            with open(os.path.join(output_dir, "NYSE_barchart_enriched.csv"), "r", encoding="utf-8", newline="") as fh:
                nyse_rows = list(csv.DictReader(fh))
            self.assertEqual(nyse_rows[0]["barchart_fetch_ok"], "TRUE")
            self.assertEqual(nyse_rows[0]["barchart_missing_fields"], "")


if __name__ == "__main__":
    unittest.main()
