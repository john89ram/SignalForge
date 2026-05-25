import csv
import json
import os
import tempfile
import unittest

from stages.stage1.code.step4_complete_stage1_output import run_stage1_step4_complete_output


class Stage1Step4CompleteOutputTests(unittest.TestCase):
    def _write_enriched_csv(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fieldnames = [
            "symbol",
            "master_exchange",
            "barchart_implied_volatility",
            "barchart_historical_volatility",
            "barchart_iv_percentile",
            "barchart_iv_rank",
        ]
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_run_stage1_step4_merges_filters_logs_and_copies_stage2_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "barchart_enrichment")
            output_dir = os.path.join(tmpdir, "stage1_output")
            stage2_input_dir = os.path.join(tmpdir, "stage2", "input")
            audit_log = os.path.join(tmpdir, "audit", "stage1_step4_complete_output.jsonl")

            self._write_enriched_csv(
                os.path.join(input_dir, "NASDAQ_barchart_enriched.csv"),
                [
                    {
                        "symbol": "AAA",
                        "master_exchange": "NASDAQ",
                        "barchart_implied_volatility": "80.0",
                        "barchart_historical_volatility": "45",
                        "barchart_iv_percentile": "70",
                        "barchart_iv_rank": "60",
                    },
                    {
                        "symbol": "BBB",
                        "master_exchange": "NASDAQ",
                        "barchart_implied_volatility": "74.99",
                        "barchart_historical_volatility": "45",
                        "barchart_iv_percentile": "70",
                        "barchart_iv_rank": "60",
                    },
                ],
            )
            self._write_enriched_csv(
                os.path.join(input_dir, "NYSE_barchart_enriched.csv"),
                [
                    {
                        "symbol": "CCC",
                        "master_exchange": "NYSE",
                        "barchart_implied_volatility": "75%",
                        "barchart_historical_volatility": "45",
                        "barchart_iv_percentile": "70",
                        "barchart_iv_rank": "60",
                    },
                    {
                        "symbol": "DDD",
                        "master_exchange": "NYSE",
                        "barchart_implied_volatility": "",
                        "barchart_historical_volatility": "45",
                        "barchart_iv_percentile": "70",
                        "barchart_iv_rank": "60",
                    },
                ],
            )

            result = run_stage1_step4_complete_output(
                input_dir=input_dir,
                output_dir=output_dir,
                stage2_input_dir=stage2_input_dir,
                audit_log_path=audit_log,
                min_implied_volatility=75.0,
            )

            self.assertEqual(result.total_input_rows, 4)
            self.assertEqual(result.pass_rows, 2)
            self.assertEqual(result.fail_rows, 2)
            self.assertTrue(os.path.exists(result.merged_csv_path))
            self.assertTrue(os.path.exists(result.stage1_pass_csv_path))
            self.assertTrue(os.path.exists(result.stage1_fail_csv_path))
            self.assertTrue(os.path.exists(result.stage2_input_csv_path))

            with open(result.stage1_pass_csv_path, "r", encoding="utf-8", newline="") as fh:
                pass_rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in pass_rows], ["AAA", "CCC"])
            self.assertEqual(pass_rows[0]["stage1_step4_verdict"], "PASS")
            self.assertEqual(pass_rows[1]["stage1_step4_implied_volatility"], "75.0")

            with open(result.stage1_fail_csv_path, "r", encoding="utf-8", newline="") as fh:
                fail_rows = list(csv.DictReader(fh))
            self.assertEqual([row["stage1_step4_fail_reason"] for row in fail_rows], ["implied_volatility_below_75.0", "missing_implied_volatility"])

            with open(result.stage2_input_csv_path, "r", encoding="utf-8", newline="") as fh:
                stage2_rows = list(csv.DictReader(fh))
            self.assertEqual(stage2_rows, pass_rows)

            with open(audit_log, "r", encoding="utf-8") as fh:
                audit_event = json.loads(fh.read().strip())
            self.assertEqual(audit_event["event"], "stage1_step4_complete_output_complete")
            self.assertEqual(audit_event["total_input_rows"], 4)
            self.assertEqual(audit_event["pass_rows"], 2)
            self.assertEqual(audit_event["stage2_input_csv_path"], result.stage2_input_csv_path)


if __name__ == "__main__":
    unittest.main()
