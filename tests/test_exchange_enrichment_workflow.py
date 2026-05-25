import csv
import json
import os
import tempfile
import unittest
from collections import defaultdict

import exchange_enrichment_workflow as workflow
from pipeline_logging import configure_logging
from screener import BarchartSnapshot, OptionsSnapshot, QuoteSnapshot, TickerAnalysis


class ExchangeEnrichmentWorkflowTests(unittest.TestCase):
    def _analysis(self, symbol, *, price=25.0, market_cap=2_000_000_000, implied_vol=95.0, options_volume=20_000, open_interest=5_000, spread=0.10, stage1_pass=True, reasons=None):
        quote = QuoteSnapshot(symbol=symbol, price=price, market_cap=market_cap, sector="Technology", industry="Software")
        barchart = BarchartSnapshot(
            implied_volatility=implied_vol,
            historical_volatility=110.0,
            iv_percentile=77.0,
            iv_rank=55.0,
            expected_move=4.2,
        )
        options = OptionsSnapshot(total_volume=options_volume, total_open_interest=open_interest, atm_bid_ask_spread=spread)
        return TickerAnalysis(
            symbol=symbol,
            quote=quote,
            barchart=barchart,
            options=options,
            stage1_pass=stage1_pass,
            stage1_reasons=list(reasons or []),
        )

    def test_enrich_exchange_csv_marks_missing_fields(self):
        calls = defaultdict(int)

        def fetcher(symbol):
            calls[symbol] += 1
            if symbol == "AAA":
                return self._analysis(symbol)
            return self._analysis(symbol, implied_vol=None, options_volume=None, open_interest=None, stage1_pass=False, reasons=["missing premium fields"])

        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "NYSE.csv")
            output_csv = os.path.join(tmpdir, "NYSE_enriched.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "AAA", "NYSE", "Technology", "Software", "25.00", "24.90", "2000000", "1500000", "2000000000"])
                writer.writerow([2, "BBB", "NYSE", "Technology", "Software", "35.00", "34.90", "2000000", "1500000", "3000000000"])

            result = workflow.enrich_exchange_csv(input_csv, output_csv, fetch_analysis=fetcher, workers=1)
            self.assertEqual(result.input_rows, 2)
            self.assertEqual(result.output_rows, 2)
            self.assertGreaterEqual(calls["AAA"], 1)
            self.assertGreaterEqual(calls["BBB"], 1)

            with open(output_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["AAA", "BBB"])
            bbb = next(row for row in rows if row["symbol"] == "BBB")
            self.assertIn("implied_volatility", bbb["missing_fields"])
            self.assertIn("options_volume", bbb["missing_fields"])
            self.assertIn("open_interest", bbb["missing_fields"])

    def test_enrich_exchange_csv_emits_progress_events(self):
        def fetcher(symbol):
            return self._analysis(symbol)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "NASDAQ.csv")
            output_csv = os.path.join(tmpdir, "NASDAQ_enriched.csv")
            log_file = os.path.join(tmpdir, "log.jsonl")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "AAA", "NASDAQ", "Technology", "Software", "25.00", "24.90", "2000000", "1500000", "2000000000"])
                writer.writerow([2, "BBB", "NASDAQ", "Technology", "Software", "35.00", "34.90", "2000000", "1500000", "3000000000"])

            logger = configure_logging(log_file=log_file)
            result = workflow.enrich_exchange_csv(input_csv, output_csv, fetch_analysis=fetcher, workers=1, logger=logger)
            self.assertEqual(result.output_rows, 2)

            with open(log_file, "r", encoding="utf-8") as fh:
                events = [json.loads(line) for line in fh if line.strip()]

            progress_events = [event for event in events if event["event"] == "exchange_enrich_progress"]
            self.assertEqual(len(progress_events), 2)
            self.assertEqual(progress_events[-1]["exchange"], "NASDAQ")
            self.assertEqual(progress_events[-1]["completed_rows"], 2)
            self.assertEqual(progress_events[-1]["total_rows"], 2)
            self.assertEqual(progress_events[-1]["percent_complete"], 100.0)

    def test_verify_enriched_exchange_csv_repairs_missing_rows(self):
        def fetcher(symbol):
            if symbol == "AAA":
                return self._analysis(symbol)
            return self._analysis(symbol)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "NYSE_enriched.csv")
            output_csv = os.path.join(tmpdir, "NYSE_repaired.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap", "implied_volatility", "historical_volatility", "iv_percentile", "iv_rank", "expected_move", "options_volume", "open_interest", "atm_bid_ask_spread", "stage1_pass", "stage1_reasons", "source_input_file", "fetch_error", "missing_fields"])
                writer.writerow([1, "AAA", "NYSE", "Technology", "Software", "25.00", "24.90", "2000000", "1500000", "2000000000", "95.0", "110.0", "77.0", "55.0", "4.2", "20000", "5000", "0.10", "PASS", "", "NYSE.csv", "", ""])
                writer.writerow([2, "BBB", "NYSE", "Technology", "Software", "35.00", "34.90", "2000000", "1500000", "3000000000", "", "110.0", "77.0", "55.0", "4.2", "", "", "", "KILL", "missing premium fields", "NYSE.csv", "", "implied_volatility,options_volume,open_interest,atm_bid_ask_spread"])

            result = workflow.verify_enriched_exchange_csv(input_csv, output_csv, fetch_analysis=fetcher, retry_workers=1)
            self.assertEqual(result.input_rows, 2)
            self.assertEqual(result.missing_rows, 1)
            self.assertEqual(result.repaired_rows, 1)
            self.assertEqual(result.unresolved_rows, 0)
            with open(output_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            bbb = next(row for row in rows if row["symbol"] == "BBB")
            self.assertEqual(bbb["missing_fields"], "")
            self.assertEqual(bbb["stage1_pass"], "PASS")

    def test_full_workflow_enriches_verifies_and_repairs_per_exchange(self):
        call_counts = defaultdict(int)

        def fetcher(symbol):
            call_counts[symbol] += 1
            if symbol == "BBB" and call_counts[symbol] == 1:
                return self._analysis(symbol, implied_vol=None, options_volume=None, open_interest=None, stage1_pass=False, reasons=["first pass missing"])
            return self._analysis(symbol)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "split")
            output_dir = os.path.join(tmpdir, "out")
            os.makedirs(input_dir, exist_ok=True)

            with open(os.path.join(input_dir, "NYSE.csv"), "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "AAA", "NYSE", "Technology", "Software", "25.00", "24.90", "2000000", "1500000", "2000000000"])

            with open(os.path.join(input_dir, "NASDAQ-GS.csv"), "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "BBB", "NASDAQ-GS", "Technology", "Software", "35.00", "34.90", "2000000", "1500000", "3000000000"])

            result = workflow.run_exchange_workflow(
                input_dir,
                output_dir,
                mode="full",
                fetch_analysis=fetcher,
                workers=1,
                retry_workers=1,
            )

            self.assertEqual(result.mode, "full")
            self.assertEqual(len(result.enriched_files), 2)
            self.assertEqual(len(result.repaired_files), 2)
            self.assertTrue(os.path.exists(result.report_csv_path))
            self.assertTrue(os.path.exists(result.retry_queue_csv_path))
            self.assertTrue(os.path.exists(result.unresolved_csv_path))
            self.assertTrue(os.path.exists(result.stage1_pass_csv_path))
            self.assertTrue(os.path.exists(result.stage1_fail_csv_path))

            with open(result.report_csv_path, "r", encoding="utf-8") as fh:
                report_rows = list(csv.DictReader(fh))
            self.assertEqual(len(report_rows), 4)

            with open(result.stage1_pass_csv_path, "r", encoding="utf-8") as fh:
                pass_rows = list(csv.DictReader(fh))
            with open(result.stage1_fail_csv_path, "r", encoding="utf-8") as fh:
                fail_rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in pass_rows], ["AAA", "BBB"])
            self.assertEqual(fail_rows, [])

            with open(os.path.join(output_dir, "NASDAQ-GS_repaired.csv"), "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            bbb = rows[0]
            self.assertEqual(bbb["missing_fields"], "")
            self.assertEqual(bbb["stage1_pass"], "PASS")

            with open(result.retry_queue_csv_path, "r", encoding="utf-8") as fh:
                retry_rows = list(csv.DictReader(fh))
            self.assertEqual(len(retry_rows), 1)
            self.assertEqual(retry_rows[0]["symbol"], "BBB")

            with open(result.unresolved_csv_path, "r", encoding="utf-8") as fh:
                unresolved_rows = list(csv.DictReader(fh))
            self.assertEqual(unresolved_rows, [])


if __name__ == "__main__":
    unittest.main()
