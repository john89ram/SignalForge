import csv
import os
import tempfile
import unittest

from stages.stage1.code.step2_exchange_split import (
    normalize_exchange,
    run_stage1_step2_exchange_split,
    split_rows_by_exchange,
)


class Stage1Step2ExchangeSplitTests(unittest.TestCase):
    def test_normalize_exchange_groups_expected_variants(self):
        self.assertEqual(normalize_exchange("NYSE"), "NYSE")
        self.assertEqual(normalize_exchange("NYSE American"), "NYSE")
        self.assertEqual(normalize_exchange("NASDAQ"), "NASDAQ")
        self.assertEqual(normalize_exchange("NASDAQ-GS"), "NASDAQ")
        self.assertEqual(normalize_exchange(""), "UNKNOWN")

    def test_split_rows_by_exchange_groups_nyse_and_nasdaq(self):
        rows = [
            {"symbol": "AAA", "master_exchange": "NYSE"},
            {"symbol": "BBB", "master_exchange": "NASDAQ"},
            {"symbol": "CCC", "master_exchange": "NASDAQ-GS"},
            {"symbol": "DDD", "master_exchange": "OTC"},
        ]
        grouped, unknown = split_rows_by_exchange(rows)
        self.assertEqual([row["symbol"] for row in grouped["NYSE"]], ["AAA"])
        self.assertEqual([row["symbol"] for row in grouped["NASDAQ"]], ["BBB", "CCC"])
        self.assertEqual([row["symbol"] for row in unknown], ["DDD"])

    def test_run_stage1_step2_exchange_split_writes_csvs_and_audit_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "stage1_step1.csv")
            output_dir = os.path.join(tmpdir, "splits")
            audit_log = os.path.join(tmpdir, "audit.jsonl")
            rows = [
                {"symbol": "AAA", "master_exchange": "NYSE", "price_proxy": "25"},
                {"symbol": "BBB", "master_exchange": "NASDAQ", "price_proxy": "35"},
            ]
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            result = run_stage1_step2_exchange_split(
                input_csv_path=input_csv,
                output_dir=output_dir,
                audit_log_path=audit_log,
            )

            self.assertEqual(result.input_rows, 2)
            self.assertEqual(result.nyse_rows, 1)
            self.assertEqual(result.nasdaq_rows, 1)
            self.assertEqual(result.unknown_rows, 0)
            self.assertTrue(os.path.exists(result.nyse_csv_path))
            self.assertTrue(os.path.exists(result.nasdaq_csv_path))
            self.assertTrue(os.path.exists(audit_log))

            with open(result.nyse_csv_path, "r", encoding="utf-8", newline="") as fh:
                nyse_rows = list(csv.DictReader(fh))
            with open(result.nasdaq_csv_path, "r", encoding="utf-8", newline="") as fh:
                nasdaq_rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in nyse_rows], ["AAA"])
            self.assertEqual([row["symbol"] for row in nasdaq_rows], ["BBB"])


if __name__ == "__main__":
    unittest.main()
