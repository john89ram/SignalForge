import os
import tempfile
import unittest

import nasdaq_market_cap_census as census


class StubHTTP:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append(url)
        if "offset=0" in url:
            payload = {
                "data": {
                    "totalrecords": 3,
                    "table": {
                        "rows": [
                            {"symbol": "AAA", "name": "Alpha", "lastsale": "$10.00", "netchange": "+1.00", "pctchange": "+10%", "marketCap": "2,000,000,000", "url": "/market-activity/stocks/aaa"},
                            {"symbol": "BBB", "name": "Beta", "lastsale": "$20.00", "netchange": "+2.00", "pctchange": "+10%", "marketCap": "NA", "url": "/market-activity/stocks/bbb"},
                        ]
                    },
                }
            }
        else:
            payload = {
                "data": {
                    "totalrecords": 3,
                    "table": {
                        "rows": [
                            {"symbol": "CCC", "name": "Gamma", "lastsale": "$30.00", "netchange": "+3.00", "pctchange": "+10%", "marketCap": "900,000,000", "url": "/market-activity/stocks/ccc"},
                        ]
                    },
                }
            }

        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        return Resp(payload)


class NasdaqMarketCapCensusTests(unittest.TestCase):
    def test_run_nasdaq_market_cap_census_paginates_and_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            http = StubHTTP()
            result = census.run_nasdaq_market_cap_census(
                output_dir=tmpdir,
                min_market_cap=1e9,
                page_size=2,
                show_progress=False,
                http=http,
            )

            self.assertEqual(result.total_records, 3)
            self.assertEqual(result.fetched_rows, 3)
            self.assertEqual(result.kept_rows, 1)
            self.assertEqual(result.missing_market_cap_rows, 1)
            self.assertEqual(result.below_threshold_rows, 1)
            self.assertTrue(os.path.exists(result.raw_csv_path))
            self.assertTrue(os.path.exists(result.filtered_csv_path))

            with open(result.filtered_csv_path, "r", encoding="utf-8") as fh:
                lines = fh.read().strip().splitlines()
            self.assertIn("AAA", lines[1])
            self.assertEqual(len(lines), 2)

            self.assertEqual(len(http.calls), 2)


if __name__ == "__main__":
    unittest.main()
