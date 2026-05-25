import csv
import io
import os
import tempfile
import unittest
from pathlib import Path

import nasdaq_summary_archive as nasa


class StubResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class StubHTTP:
    def __init__(self, timeout=None, retries=None):
        self.timeout = timeout
        self.retries = retries
        self.session = self

    def get(self, url, timeout=None, headers=None):
        symbol = url.split("/quote/")[1].split("/")[0].upper()
        payloads = {
            "IONQ": {
                "data": {
                    "symbol": "IONQ",
                    "summaryData": {
                        "Exchange": {"label": "Exchange", "value": "NYSE"},
                        "Sector": {"label": "Sector", "value": "Technology"},
                        "Industry": {"label": "Industry", "value": "EDP Services"},
                        "OneYrTarget": {"label": "1 Year Target", "value": "$65.00"},
                        "TodayHighLow": {"label": "Today's High/Low", "value": "$62.50/$58.10"},
                        "ShareVolume": {"label": "Share Volume", "value": "52,650,276"},
                        "AverageVolume": {"label": "Average Volume", "value": "41,000,000"},
                        "PreviousClose": {"label": "Previous Close", "value": "$58.89"},
                        "FiftTwoWeekHighLow": {"label": "52 Week High/Low", "value": "$84.64/$25.89"},
                        "MarketCap": {"label": "Market Cap", "value": "23,754,899,491"},
                    },
                    "bidAsk": {
                        "Bid * Size": {"label": "Bid * Size", "value": "12 x 400"},
                        "Ask * Size": {"label": "Ask * Size", "value": "13 x 300"},
                    },
                },
                "status": {"rCode": 200},
            },
            "AAPL": {
                "data": {
                    "symbol": "AAPL",
                    "summaryData": {
                        "Exchange": {"label": "Exchange", "value": "NASDAQ"},
                        "Sector": {"label": "Sector", "value": "Technology"},
                        "Industry": {"label": "Industry", "value": "Consumer Electronics"},
                        "OneYrTarget": {"label": "1 Year Target", "value": "$250.00"},
                        "TodayHighLow": {"label": "Today's High/Low", "value": "$210.00/$205.00"},
                        "ShareVolume": {"label": "Share Volume", "value": "27,306,470.50"},
                        "AverageVolume": {"label": "Average Volume", "value": "30,000,000"},
                        "PreviousClose": {"label": "Previous Close", "value": "$207.41"},
                        "FiftTwoWeekHighLow": {"label": "52 Week High/Low", "value": "$260.00/$180.00"},
                        "MarketCap": {"label": "Market Cap", "value": "328,144,063,412"},
                    },
                    "bidAsk": {
                        "Bid * Size": {"label": "Bid * Size", "value": "N/A"},
                        "Ask * Size": {"label": "Ask * Size", "value": "N/A"},
                    },
                },
                "status": {"rCode": 200},
            },
        }
        if symbol not in payloads:
            raise AssertionError(f"Unexpected URL: {url}")
        return StubResponse(payloads[symbol])


class NasdaqSummaryArchiveTests(unittest.TestCase):
    def test_make_summary_row_parses_nasdaq_payload(self):
        symbol = nasa.SymbolRow(symbol="IONQ", exchange="NYSE", name="IonQ, Inc.", cik="0001824920")
        payload = StubHTTP().get("https://api.nasdaq.com/api/quote/IONQ/summary?assetclass=stocks").json()
        row = nasa._make_summary_row(
            symbol,
            payload,
            url="https://api.nasdaq.com/api/quote/IONQ/summary?assetclass=stocks",
            json_path="/tmp/IONQ/nasdaq_summary.json",
            status_code=200,
            elapsed_seconds=0.1234,
        )

        self.assertEqual(row.symbol, "IONQ")
        self.assertEqual(row.master_exchange, "NYSE")
        self.assertEqual(row.name, "IonQ, Inc.")
        self.assertEqual(row.api_exchange, "NYSE")
        self.assertEqual(row.sector, "Technology")
        self.assertEqual(row.industry, "EDP Services")
        self.assertEqual(row.one_yr_target, 65.0)
        self.assertEqual(row.today_high, 62.5)
        self.assertEqual(row.today_low, 58.1)
        self.assertEqual(row.share_volume, 52650276.0)
        self.assertEqual(row.average_volume, 41000000.0)
        self.assertEqual(row.previous_close, 58.89)
        self.assertEqual(row.fifty_two_week_high, 84.64)
        self.assertEqual(row.fifty_two_week_low, 25.89)
        self.assertEqual(row.market_cap, 23754899491.0)
        self.assertEqual(row.bid_size_raw, "12 x 400")
        self.assertEqual(row.ask_size_raw, "13 x 300")
        self.assertTrue(row.ok)

    def test_run_writes_flat_csv_and_raw_json(self):
        old_http = nasa.HTTP
        try:
            nasa.HTTP = StubHTTP
            with tempfile.TemporaryDirectory() as tmpdir:
                input_csv = os.path.join(tmpdir, "master.csv")
                output_csv = os.path.join(tmpdir, "flat.csv")
                with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["symbol", "exchange", "name", "cik"])
                    writer.writerow(["IONQ", "NYSE", "IonQ, Inc.", "0001824920"])
                    writer.writerow(["AAPL", "NASDAQ", "Apple Inc.", "0000320193"])

                result = nasa.run_nasdaq_summary_archive(
                    input_csv=input_csv,
                    output_dir=os.path.join(tmpdir, "archive"),
                    workers=1,
                    retries=0,
                    csv_path=output_csv,
                )

                self.assertEqual(result.total_symbols, 2)
                self.assertEqual(result.completed_symbols, 2)
                self.assertEqual(result.ok_symbols, 2)
                self.assertEqual(result.failed_symbols, 0)
                self.assertTrue(Path(result.csv_path).exists())

                with open(output_csv, "r", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual([row["symbol"] for row in rows], ["AAPL", "IONQ"])
                self.assertEqual(rows[0]["market_cap"], "328144063412.0")
                self.assertEqual(rows[1]["share_volume"], "52650276.0")
                self.assertEqual(rows[1]["api_exchange"], "NYSE")
                self.assertEqual(rows[1]["today_high"], "62.5")
                self.assertEqual(rows[1]["today_low"], "58.1")

                archive_dir = Path(result.snapshot_dir)
                self.assertTrue((archive_dir / "symbols" / "AAPL" / "nasdaq_summary.json").exists())
                self.assertTrue((archive_dir / "symbols" / "IONQ" / "nasdaq_summary.json").exists())
        finally:
            nasa.HTTP = old_http

    def test_main_supports_direct_csv_path(self):
        old_http = nasa.HTTP
        try:
            nasa.HTTP = StubHTTP
            with tempfile.TemporaryDirectory() as tmpdir:
                input_csv = os.path.join(tmpdir, "master.csv")
                output_csv = os.path.join(tmpdir, "direct.csv")
                with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(["symbol", "exchange", "name", "cik"])
                    writer.writerow(["IONQ", "NYSE", "IonQ, Inc.", "0001824920"])
                rc = nasa.main([
                    "--input-csv",
                    input_csv,
                    "--output-dir",
                    os.path.join(tmpdir, "archive"),
                    "--csv-path",
                    output_csv,
                    "--workers",
                    "1",
                    "--retries",
                    "0",
                ])
                self.assertEqual(rc, 0)
                self.assertTrue(Path(output_csv).exists())
                with open(output_csv, "r", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["symbol"], "IONQ")
        finally:
            nasa.HTTP = old_http
