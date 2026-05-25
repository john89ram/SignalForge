import csv
import os
import tempfile
import unittest

from stages.stage1.code.step1_rough_filter import (
    RoughFilterThresholds,
    apply_rough_filter,
    run_stage1_step1_rough_filter,
)


class Stage1Step1RoughFilterTests(unittest.TestCase):
    def test_apply_rough_filter_uses_market_cap_price_and_volume_gates(self):
        rows = [
            {
                "symbol": "AAA",
                "name": "Alpha",
                "master_exchange": "NYSE",
                "previous_close": "25.00",
                "share_volume": "1,500,000",
                "market_cap": "2,000,000,000",
            },
            {
                "symbol": "LOWCAP",
                "previous_close": "25.00",
                "share_volume": "1,500,000",
                "market_cap": "999,999,999",
            },
            {
                "symbol": "PRICELOW",
                "previous_close": "9.99",
                "share_volume": "1,500,000",
                "market_cap": "2,000,000,000",
            },
            {
                "symbol": "VOLUMELOW",
                "previous_close": "25.00",
                "share_volume": "999,999",
                "market_cap": "2,000,000,000",
            },
        ]

        survivors, stats = apply_rough_filter(rows)

        self.assertEqual([row["symbol"] for row in survivors], ["AAA"])
        self.assertEqual(stats["input_rows"], 4)
        self.assertEqual(stats["market_cap_survivors"], 3)
        self.assertEqual(stats["price_survivors"], 2)
        self.assertEqual(stats["volume_survivors"], 1)

    def test_run_stage1_step1_rough_filter_writes_expected_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "input.csv")
            output_csv = os.path.join(tmpdir, "output.csv")
            rows = [
                {
                    "symbol": "BBB",
                    "name": "Beta",
                    "master_exchange": "NASDAQ",
                    "sector": "Tech",
                    "industry": "Software",
                    "previous_close": "$75.00",
                    "share_volume": "1,000,000",
                    "market_cap": "1,000,000,000",
                    "one_yr_target": "$90.00",
                    "url": "https://example.test/bbb",
                    "json_path": "/tmp/bbb.json",
                },
                {
                    "symbol": "AAA",
                    "name": "Alpha",
                    "master_exchange": "NYSE",
                    "sector": "Finance",
                    "industry": "Banks",
                    "previous_close": "$10.00",
                    "share_volume": "2,000,000",
                    "market_cap": "2,000,000,000",
                    "one_yr_target": "$20.00",
                    "url": "https://example.test/aaa",
                    "json_path": "/tmp/aaa.json",
                },
            ]
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            result = run_stage1_step1_rough_filter(
                input_csv_path=input_csv,
                output_csv_path=output_csv,
                thresholds=RoughFilterThresholds(),
            )

            self.assertEqual(result.input_rows, 2)
            self.assertEqual(result.volume_survivors, 2)
            self.assertTrue(os.path.exists(output_csv))
            with open(output_csv, "r", encoding="utf-8", newline="") as fh:
                out_rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in out_rows], ["AAA", "BBB"])
            self.assertEqual(out_rows[0]["price_proxy"], "10.0")


if __name__ == "__main__":
    unittest.main()
