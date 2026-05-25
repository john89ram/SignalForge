import csv
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import market_cap_census as census


class CensusTests(unittest.TestCase):
    def test_fetch_census_row_filters_and_parses_market_cap(self):
        class StubResp:
            def __init__(self, payload=None, text=None):
                self._payload = payload
                self.text = text or ""

            def json(self):
                return self._payload

        class StubHTTP:
            def get(self, url, headers=None):
                if "api.nasdaq.com/api/quote/PLTR/summary" in url:
                    return StubResp(
                        {
                            "data": {
                                "symbol": "PLTR",
                                "summaryData": {
                                    "Exchange": {"value": "NASDAQ-GS"},
                                    "Sector": {"value": "Technology"},
                                    "Industry": {"value": "Software"},
                                    "PreviousClose": {"value": "$137.41"},
                                    "TodayHighLow": {"value": "$139.02/$134.30"},
                                    "ShareVolume": {"value": "27,306,470.50"},
                                    "AverageVolume": {"value": "30,000,000"},
                                    "MarketCap": {"value": "328,144,063,412"},
                                },
                            }
                        }
                    )
                if "barchart.com/stocks/quotes/PLTR/overview" in url:
                    return StubResp(text='''
                        <span class="left">Implied Volatility</span><span class="right"> 95.25% </span>
                        <span class="left">IV Rank</span><span class="right"> 50.00% </span>
                        <span class="left">IV Percentile</span><span class="right"> 77.00% </span>
                    ''')
                if "finviz.com/quote.ashx?t=PLTR&ta=1&p=d&ty=oc" in url:
                    return StubResp(text='''
                        "currentExpiry":"2026-05-29"
                        "ticker":"PLTR","options":[
                            {"exDate":260529,"type":"call","strike":139,"lastVolume":1200,"openInterest":2400,"bidPrice":1.2,"askPrice":1.4},
                            {"exDate":260529,"type":"put","strike":139,"lastVolume":800,"openInterest":1600,"bidPrice":1.1,"askPrice":1.3}
                        ]
                    ''')
                raise AssertionError(f"Unexpected URL: {url}")

        old_http = census.HTTP
        try:
            census.HTTP = lambda: StubHTTP()
            row = census.fetch_census_row("PLTR", min_market_cap=1e9)
        finally:
            census.HTTP = old_http

        self.assertIsNotNone(row)
        self.assertEqual(row.symbol, "PLTR")
        self.assertEqual(row.exchange, "NASDAQ-GS")
        self.assertEqual(row.sector, "Technology")
        self.assertEqual(row.industry, "Software")
        self.assertEqual(row.previous_close, 137.41)
        self.assertEqual(row.price, 139.02)
        self.assertEqual(row.share_volume, 27306470.5)
        self.assertEqual(row.average_volume, 30000000.0)
        self.assertEqual(row.market_cap, 328144063412.0)
        self.assertEqual(row.implied_volatility, 95.25)
        self.assertEqual(row.options_volume, 2000)
        self.assertEqual(row.open_interest, 4000)

    def test_scanner_run_writes_csv_and_returns_runtime(self):
        def fake_fetch(sym, min_market_cap=1e9, http=None):
            mapping = {
                "AAA": census.CensusRow(symbol="AAA", exchange="NASDAQ-GS", sector="Tech", market_cap=2e9, price=10.0),
                "BBB": census.CensusRow(symbol="BBB", exchange="NYSE", sector="Finance", market_cap=3e9, price=20.0),
                "CCC": None,
            }
            return mapping[sym]

        scanner = census.MarketCapCensusScanner(http=None, min_market_cap=1e9, workers=1, fetch_row=fake_fetch)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "census.csv")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = scanner.run(["AAA", "BBB", "CCC"], csv_path=csv_path, universe_label="unit test")
                census.print_run_summary(result)
            self.assertEqual(result.tickers_scanned, 3)
            self.assertEqual(len(result.survivors), 2)
            self.assertGreaterEqual(result.runtime_seconds, 0.0)
            output = buffer.getvalue()
            self.assertIn("Progress:", output)
            self.assertIn("100%)", output)
            self.assertIn("Tickers scanned: 3", output)
            self.assertIn("Market cap >= $1,000,000,000 survivors: 2", output)
            self.assertIn("Runtime:", output)
            with open(csv_path, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["BBB", "AAA"])
            self.assertEqual([row["rank"] for row in rows], ["1", "2"])

    def test_main_writes_market_cap_csv_and_prints_runtime(self):
        old_load = census.load_all_us_tickers
        old_fetch = census.fetch_census_row
        try:
            census.load_all_us_tickers = lambda http: ["AAA", "BBB", "CCC"]
            census.fetch_census_row = lambda sym, min_market_cap=1e9, http=None: {
                "AAA": census.CensusRow(symbol="AAA", exchange="NASDAQ-GS", sector="Tech", market_cap=2e9, price=10.0),
                "BBB": census.CensusRow(symbol="BBB", exchange="NYSE", sector="Finance", market_cap=3e9, price=20.0),
                "CCC": None,
            }[sym]
            with tempfile.TemporaryDirectory() as tmpdir:
                csv_path = os.path.join(tmpdir, "census.csv")
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    rc = census.main(["--all-us", "--csv-path", csv_path])
                self.assertEqual(rc, 0)
                output = buffer.getvalue()
                self.assertIn("Progress:", output)
                self.assertIn("100%)", output)
                self.assertIn("Tickers scanned: 3", output)
                self.assertIn("Market cap >= $1,000,000,000 survivors: 2", output)
                self.assertIn("Runtime:", output)
                with open(csv_path, "r", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual([row["symbol"] for row in rows], ["BBB", "AAA"])
                self.assertEqual([row["rank"] for row in rows], ["1", "2"])
        finally:
            census.load_all_us_tickers = old_load
            census.fetch_census_row = old_fetch

    def test_price_filter_filters_csv_between_10_and_75(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "census.csv")
            output_csv = os.path.join(tmpdir, "price-filtered.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "LOW", "NYSE", "Tech", "Software", "9.99", "9.90", "100", "100", "2000000000"])
                writer.writerow([2, "MID", "NASDAQ", "Tech", "Software", "10.00", "9.95", "100", "100", "3000000000"])
                writer.writerow([3, "HIGH", "NASDAQ", "Tech", "Software", "75.00", "74.50", "100", "100", "4000000000"])
                writer.writerow([4, "TOO_HIGH", "NYSE", "Tech", "Software", "75.01", "75.00", "100", "100", "5000000000"])

            filterer = census.CensusCSVPriceFilter(min_price=10, max_price=75)
            result = filterer.run(input_csv, output_csv)

            self.assertEqual(result.input_rows, 4)
            self.assertEqual(result.filtered_rows, 2)
            self.assertEqual(result.output_csv_path, output_csv)
            with open(output_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["MID", "HIGH"])

    def test_volume_filter_filters_csv_at_or_above_one_million(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "census.csv")
            output_csv = os.path.join(tmpdir, "volume-filtered.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "LOWVOL", "NYSE", "Tech", "Software", "25.00", "24.90", "999999", "100", "2000000000"])
                writer.writerow([2, "MIDDLE", "NASDAQ", "Tech", "Software", "35.00", "34.95", "1000000", "100", "3000000000"])
                writer.writerow([3, "HIGHVOL", "NASDAQ", "Tech", "Software", "45.00", "44.50", "2500000", "100", "4000000000"])

            filterer = census.CensusCSVVolumeFilter(min_volume=1_000_000)
            result = filterer.run(input_csv, output_csv)

            self.assertEqual(result.input_rows, 3)
            self.assertEqual(result.filtered_rows, 2)
            self.assertEqual(result.output_csv_path, output_csv)
            with open(output_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["MIDDLE", "HIGHVOL"])

    def test_open_interest_filter_filters_csv_at_or_above_one_thousand(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "census.csv")
            output_csv = os.path.join(tmpdir, "open-interest-filtered.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap", "open_interest"])
                writer.writerow([1, "LOWOI", "NYSE", "Tech", "Software", "25.00", "24.90", "100000", "100", "2000000000", "999"])
                writer.writerow([2, "MIDDLE", "NASDAQ", "Tech", "Software", "35.00", "34.95", "100000", "100", "3000000000", "1000"])
                writer.writerow([3, "HIGHOI", "NASDAQ", "Tech", "Software", "45.00", "44.50", "250000", "100", "4000000000", "2500"])

            filterer = census.CensusCSVOpenInterestFilter(min_open_interest=1_000)
            result = filterer.run(input_csv, output_csv)

            self.assertEqual(result.input_rows, 3)
            self.assertEqual(result.filtered_rows, 2)
            self.assertEqual(result.output_csv_path, output_csv)
            with open(output_csv, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["MIDDLE", "HIGHOI"])

    def test_shrink_pipeline_prints_progress_and_chains_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "census.csv")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "stock_volume_today", "share_volume", "average_volume", "implied_volatility", "iv_rank", "iv_percentile", "historical_volatility", "expected_move", "options_volume", "open_interest", "atm_bid_ask_spread", "market_cap"])
                writer.writerow([1, "LOWPRICE", "NYSE", "Tech", "Software", "9.99", "9.90", "2000000", "2000000", "1500000", "80", "40", "60", "70", "5", "20000", "5000", "0.10", "2000000000"])
                writer.writerow([2, "MIDPASS", "NASDAQ", "Tech", "Software", "25.00", "24.90", "2000000", "2000000", "1500000", "90", "50", "70", "75", "6", "30000", "1000", "0.10", "3000000000"])
                writer.writerow([3, "MIDFAILOI", "NASDAQ", "Tech", "Software", "35.00", "34.90", "2000000", "2000000", "1500000", "95", "60", "80", "85", "7", "40000", "999", "0.10", "4000000000"])
                writer.writerow([4, "HIGHPRICE", "NYSE", "Tech", "Software", "80.00", "79.50", "3000000", "3000000", "2000000", "85", "45", "65", "72", "4", "25000", "2500", "0.10", "5000000000"])

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = census.run_census_shrink_pipeline(input_csv)

            output = buffer.getvalue()
            self.assertIn("Starting shrink pipeline", output)
            self.assertIn("After price filter", output)
            self.assertIn("After volume filter", output)
            self.assertIn("After open-interest filter", output)
            self.assertIn("Runtime:", output)
            self.assertEqual(result.input_rows, 4)
            self.assertEqual(result.price_result.filtered_rows, 2)
            self.assertEqual(result.volume_result.filtered_rows, 2)
            self.assertEqual(result.open_interest_result.filtered_rows, 1)
            with open(result.final_csv_path, "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["MIDPASS"])

    def test_split_csv_by_exchange_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = os.path.join(tmpdir, "volume.csv")
            output_dir = os.path.join(tmpdir, "exchange-splits")
            with open(input_csv, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["rank", "symbol", "exchange", "sector", "industry", "price", "previous_close", "share_volume", "average_volume", "market_cap"])
                writer.writerow([1, "A1", "AMEX", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "2000000000"])
                writer.writerow([2, "N1", "NASDAQ-GM", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "3000000000"])
                writer.writerow([3, "N2", "NASDAQ-CM", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "4000000000"])
                writer.writerow([4, "N3", "NASDAQ-GS", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "5000000000"])
                writer.writerow([5, "Y1", "NYSE", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "6000000000"])
                writer.writerow([6, "U1", "", "Tech", "Software", "25.00", "24.90", "2000000", "1500000", "7000000000"])

            result = census.split_census_csv_by_exchange(input_csv, output_dir)

            self.assertEqual(result.input_rows, 6)
            self.assertIn("AMEX", result.exchange_files)
            self.assertIn("NASDAQ-GM", result.exchange_files)
            self.assertIn("NASDAQ-CM", result.exchange_files)
            self.assertIn("NASDAQ-GS", result.exchange_files)
            self.assertIn("NYSE", result.exchange_files)
            self.assertIn("UNKNOWN", result.exchange_files)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "AMEX Exchange.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NASDAQ-GM.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NASDAQ-CM.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NASDAQ-GS.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "NYSE.csv")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "UNKNOWN.csv")))
            with open(os.path.join(output_dir, "AMEX Exchange.csv"), "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["A1"])
            with open(os.path.join(output_dir, "UNKNOWN.csv"), "r", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["symbol"] for row in rows], ["U1"])



if __name__ == "__main__":
    unittest.main()
