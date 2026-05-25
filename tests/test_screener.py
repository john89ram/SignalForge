import csv
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import screener
import stage2_report
from screener import (
    BarchartSnapshot,
    OptionsSnapshot,
    QuoteSnapshot,
    SECFacts,
    TickerAnalysis,
    analyze_stage2,
    analyze_stage1_ticker,
    load_all_us_tickers,
    rank_stage1_candidates,
    sector_spread,
    stage1_filter,
    stage3_analysis,
)


class ScreenerTests(unittest.TestCase):
    def test_load_all_us_tickers_uses_sec_ticker_map_and_dedupes(self):
        class StubResp:
            def json(self):
                return {
                    "0": {"ticker": "aapl"},
                    "1": {"ticker": "msft"},
                    "2": {"ticker": "AAPL"},
                }

        class StubHTTP:
            def get(self, url, headers=None):
                return StubResp()

        self.assertEqual(load_all_us_tickers(StubHTTP()), ["AAPL", "MSFT"])

    def test_rank_stage1_candidates_orders_by_implied_volatility_then_liquidity(self):
        top = TickerAnalysis(
            symbol="TOP",
            quote=QuoteSnapshot(symbol="TOP", price=20.0, market_cap=5e9, volume=5e6),
            barchart=BarchartSnapshot(iv_rank=95.0, implied_volatility=95.0),
            options=OptionsSnapshot(total_volume=5000, total_open_interest=4000, atm_bid_ask_spread=0.3),
            stage1_pass=True,
        )
        mid = TickerAnalysis(
            symbol="MID",
            quote=QuoteSnapshot(symbol="MID", price=20.0, market_cap=5e9, volume=4e6),
            barchart=BarchartSnapshot(iv_rank=95.0, implied_volatility=90.0),
            options=OptionsSnapshot(total_volume=4000, total_open_interest=3000, atm_bid_ask_spread=0.2),
            stage1_pass=True,
        )
        low = TickerAnalysis(
            symbol="LOW",
            quote=QuoteSnapshot(symbol="LOW", price=20.0, market_cap=5e9, volume=3e6),
            barchart=BarchartSnapshot(iv_rank=85.0, implied_volatility=80.0),
            options=OptionsSnapshot(total_volume=3000, total_open_interest=2000, atm_bid_ask_spread=0.1),
            stage1_pass=True,
        )
        reject = TickerAnalysis(
            symbol="REJECT",
            quote=QuoteSnapshot(symbol="REJECT", price=20.0, market_cap=5e9, volume=6e6),
            barchart=BarchartSnapshot(iv_rank=99.0, implied_volatility=10.0),
            options=OptionsSnapshot(total_volume=6000, total_open_interest=5000, atm_bid_ask_spread=0.1),
            stage1_pass=False,
        )

        ranked = rank_stage1_candidates([low, reject, mid, top])
        self.assertEqual([a.symbol for a in ranked], ["TOP", "MID", "LOW"])

    def test_stage1_filter_uses_implied_volatility_not_iv_rank(self):
        quote = QuoteSnapshot(symbol="TEST", price=25.0, market_cap=2e9, volume=2e6)
        options = OptionsSnapshot(total_volume=2000, total_open_interest=2000, atm_bid_ask_spread=0.2)

        low_iv = BarchartSnapshot(iv_rank=60.0, implied_volatility=60.0)
        passed_low, reasons_low = stage1_filter(quote, low_iv, options)
        self.assertFalse(passed_low)
        self.assertTrue(any("implied volatility" in reason.lower() for reason in reasons_low))

        high_iv = BarchartSnapshot(iv_rank=20.0, implied_volatility=80.0)
        passed_high, reasons_high = stage1_filter(quote, high_iv, options)
        self.assertTrue(passed_high, reasons_high)

    def test_stage1_filter_is_configurable_for_price_band(self):
        quote = QuoteSnapshot(symbol="FUTU", price=94.49, market_cap=9.05e9, volume=45_000_000)
        barchart = BarchartSnapshot(iv_rank=100.0, implied_volatility=100.0)
        options = OptionsSnapshot(total_volume=83_015, total_open_interest=44_399)

        passed_default, reasons_default = stage1_filter(quote, barchart, options)
        self.assertFalse(passed_default)
        self.assertTrue(any("outside $10-$75" in reason for reason in reasons_default))

        passed_relaxed, reasons_relaxed = stage1_filter(
            quote,
            barchart,
            options,
            min_price=10,
            max_price=100,
        )
        self.assertTrue(passed_relaxed, reasons_relaxed)

    def test_all_us_csv_exports_ranked_stage1_survivors(self):
        def fake_analyze(http, sym, **kwargs):
            mapping = {
                "AAA": TickerAnalysis(
                    symbol="AAA",
                    quote=QuoteSnapshot(symbol="AAA", price=10, sector="Tech", market_cap=2e9),
                    barchart=BarchartSnapshot(iv_rank=80, implied_volatility=80),
                    options=OptionsSnapshot(total_volume=100, total_open_interest=200, atm_bid_ask_spread=0.5),
                    stage1_pass=True,
                ),
                "BBB": TickerAnalysis(
                    symbol="BBB",
                    quote=QuoteSnapshot(symbol="BBB", price=20, sector="Finance", market_cap=3e9),
                    barchart=BarchartSnapshot(iv_rank=90, implied_volatility=90),
                    options=OptionsSnapshot(total_volume=200, total_open_interest=100, atm_bid_ask_spread=0.2),
                    stage1_pass=True,
                ),
                "CCC": TickerAnalysis(
                    symbol="CCC",
                    quote=QuoteSnapshot(symbol="CCC", price=30, sector="Tech", market_cap=1e9),
                    barchart=BarchartSnapshot(iv_rank=70, implied_volatility=70),
                    options=OptionsSnapshot(total_volume=1000, total_open_interest=1000, atm_bid_ask_spread=0.1),
                    stage1_pass=False,
                ),
            }
            return mapping[sym]

        old_load = screener.load_all_us_tickers
        old_analyze = screener.analyze_stage1_ticker
        try:
            screener.load_all_us_tickers = lambda http: ["AAA", "BBB", "CCC"]
            screener.analyze_stage1_ticker = fake_analyze
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                rc = screener.main(["--all-us", "--output", "csv"])
            self.assertEqual(rc, 0)
            rows = list(csv.DictReader(io.StringIO(buffer.getvalue())))
            self.assertEqual([row["symbol"] for row in rows], ["BBB", "AAA"])
            self.assertEqual([row["rank"] for row in rows], ["1", "2"])
            self.assertEqual([row["stage1_pass"] for row in rows], ["True", "True"])
        finally:
            screener.load_all_us_tickers = old_load
            screener.analyze_stage1_ticker = old_analyze

    def test_csv_path_writes_file_without_shell_redirection(self):
        def fake_analyze(http, sym, **kwargs):
            mapping = {
                "AAA": TickerAnalysis(
                    symbol="AAA",
                    quote=QuoteSnapshot(symbol="AAA", price=10, sector="Tech", market_cap=2e9),
                    barchart=BarchartSnapshot(iv_rank=80, implied_volatility=80),
                    options=OptionsSnapshot(total_volume=100, total_open_interest=200, atm_bid_ask_spread=0.5),
                    stage1_pass=True,
                ),
                "BBB": TickerAnalysis(
                    symbol="BBB",
                    quote=QuoteSnapshot(symbol="BBB", price=20, sector="Finance", market_cap=3e9),
                    barchart=BarchartSnapshot(iv_rank=90, implied_volatility=90),
                    options=OptionsSnapshot(total_volume=200, total_open_interest=100, atm_bid_ask_spread=0.2),
                    stage1_pass=True,
                ),
            }
            return mapping[sym]

        old_load = screener.load_all_us_tickers
        old_analyze = screener.analyze_stage1_ticker
        try:
            screener.load_all_us_tickers = lambda http: ["AAA", "BBB"]
            screener.analyze_stage1_ticker = fake_analyze
            with tempfile.TemporaryDirectory() as tmpdir:
                csv_path = os.path.join(tmpdir, "survivors.csv")
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    rc = screener.main(["--all-us", "--output", "csv", "--csv-path", csv_path])
                self.assertEqual(rc, 0)
                self.assertEqual(buffer.getvalue(), "")
                with open(csv_path, "r", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                self.assertEqual([row["symbol"] for row in rows], ["BBB", "AAA"])
        finally:
            screener.load_all_us_tickers = old_load
            screener.analyze_stage1_ticker = old_analyze

    def test_stage1_only_mode_uses_fast_path_for_explicit_tickers(self):
        calls = []

        def fake_stage1(http, sym, **kwargs):
            calls.append(sym)
            return TickerAnalysis(
                symbol=sym,
                quote=QuoteSnapshot(symbol=sym, price=20, sector="Tech", market_cap=2e9, volume=2e6),
                barchart=BarchartSnapshot(iv_rank=85, implied_volatility=85),
                options=OptionsSnapshot(total_volume=2000, total_open_interest=3000, atm_bid_ask_spread=0.3),
                stage1_pass=True,
            )

        old_stage1 = screener.analyze_stage1_ticker
        old_stage2 = screener.analyze_ticker
        try:
            screener.analyze_stage1_ticker = fake_stage1
            screener.analyze_ticker = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("analyze_ticker should not be used in stage1-only mode")
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                rc = screener.main(["--tickers", "AAA,BBB", "--stage1-only", "--output", "csv"])
            self.assertEqual(rc, 0)
            self.assertEqual(calls, ["AAA", "BBB"])
            rows = list(csv.DictReader(io.StringIO(buffer.getvalue())))
            self.assertEqual([row["symbol"] for row in rows], ["AAA", "BBB"])
            self.assertEqual([row["stage3_verdict"] for row in rows], ["NO ENTRY", "NO ENTRY"])
        finally:
            screener.analyze_stage1_ticker = old_stage1
            screener.analyze_ticker = old_stage2

    def test_stage2_removed_binary_operating_floor_test_and_preserves_stage1(self):
        analysis = TickerAnalysis(
            symbol="TEST",
            quote=QuoteSnapshot(symbol="TEST", price=25.0, inst_own=40.0),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            sec=None,
        )
        analysis.stage1_pass = True

        analyze_stage2(analysis, price_history=[20.0, 21.0, 22.0, 23.0])

        self.assertNotIn("No real operating floor visible", analysis.stage2_kills)
        self.assertNotIn("event / operating floor", [test["name"] for test in analysis.stage2_tests])
        self.assertEqual(analysis.stage2_kills, [])
        self.assertEqual(len(analysis.stage2_tests), 7)
        self.assertTrue(analysis.stage1_pass)

    def test_analyze_ticker_skips_stage2_and_stage3_when_stage1_fails(self):
        calls = {"sec": 0, "history": 0, "stage2": 0, "stage3": 0}

        class DummyResponse:
            def __init__(self, text=""):
                self.text = text

        class DummyHTTP:
            def get(self, url):
                return DummyResponse()

        old_parse_finviz_quote = screener.parse_finviz_quote
        old_parse_barchart_overview = screener.parse_barchart_overview
        old_parse_finviz_options = screener.parse_finviz_options
        old_load_nasdaq_meta = screener.load_nasdaq_meta
        old_stage1_filter = screener.stage1_filter
        old_load_sec = screener.load_sec_companyfacts
        old_fetch_history = screener.fetch_nasdaq_history
        old_analyze_stage2 = screener.analyze_stage2
        old_stage3 = screener.stage3_analysis
        try:
            screener.parse_finviz_quote = lambda html, symbol: QuoteSnapshot(symbol=symbol, price=25.0, market_cap=2e9)
            screener.parse_barchart_overview = lambda html: BarchartSnapshot(iv_rank=80.0, implied_volatility=90.0)
            screener.parse_finviz_options = lambda html, price: OptionsSnapshot(total_volume=2000, total_open_interest=2000, atm_bid_ask_spread=0.2)
            screener.load_nasdaq_meta = lambda http, symbol: ("Technology", "Software")
            screener.stage1_filter = lambda q, b, o, **kwargs: (False, ["forced fail"])
            screener.load_sec_companyfacts = lambda http, symbol: calls.__setitem__("sec", calls["sec"] + 1)
            screener.fetch_nasdaq_history = lambda http, symbol, days=90: calls.__setitem__("history", calls["history"] + 1)
            screener.analyze_stage2 = lambda analysis, price_history=None: calls.__setitem__("stage2", calls["stage2"] + 1)
            screener.stage3_analysis = lambda analysis: calls.__setitem__("stage3", calls["stage3"] + 1)

            analysis = screener.analyze_ticker(DummyHTTP(), "FAIL", include_stage3=True)
            self.assertFalse(analysis.stage1_pass)
            self.assertEqual(calls, {"sec": 0, "history": 0, "stage2": 0, "stage3": 0})
        finally:
            screener.parse_finviz_quote = old_parse_finviz_quote
            screener.parse_barchart_overview = old_parse_barchart_overview
            screener.parse_finviz_options = old_parse_finviz_options
            screener.load_nasdaq_meta = old_load_nasdaq_meta
            screener.stage1_filter = old_stage1_filter
            screener.load_sec_companyfacts = old_load_sec
            screener.fetch_nasdaq_history = old_fetch_history
            screener.analyze_stage2 = old_analyze_stage2
            screener.stage3_analysis = old_stage3

    def test_stage3_analysis_returns_qc_fail_when_latest_revenue_is_zero(self):
        analysis = TickerAnalysis(
            symbol="ZERO",
            quote=QuoteSnapshot(symbol="ZERO", price=25.0, market_cap=2e9),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            sec=SECFacts(
                revenue=[("2024-12-31", 0.0)],
                op_cash_flow=[("2024-12-31", 10_000_000.0)],
                cash=[("2024-12-31", 100_000_000.0)],
                shares=[("2024-12-31", 100_000_000.0)],
            ),
        )

        stage3 = stage3_analysis(analysis)
        self.assertIsNotNone(stage3)
        assert stage3 is not None
        self.assertEqual(stage3["verdict"], "QC FAIL")
        self.assertEqual(stage3["qc_fail_reason"], "zero or missing revenue")
        self.assertIsNone(stage3["weighted_fair_value"])

    def test_load_sec_companyfacts_uses_revenue_tag_fallbacks(self):
        class StubResp:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class StubHTTP:
            def __init__(self, fact_name):
                self.fact_name = fact_name

            def get(self, url, headers=None):
                if url.endswith("company_tickers.json"):
                    return StubResp({"0": {"ticker": "FALL", "cik_str": 123456}})
                return StubResp(
                    {
                        "facts": {
                            "us-gaap": {
                                self.fact_name: {
                                    "units": {"USD": [{"end": "2024-12-31", "val": 100_000_000}]}
                                },
                                "CommonStockSharesOutstanding": {
                                    "units": {"shares": [{"end": "2024-12-31", "val": 10_000_000}]}
                                },
                            }
                        }
                    }
                )

        for fact_name in (
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ):
            with self.subTest(fact_name=fact_name):
                facts = screener.load_sec_companyfacts(StubHTTP(fact_name), "FALL")

                self.assertIsNotNone(facts)
                assert facts is not None
                self.assertEqual(facts.revenue, [("2024-12-31", 100_000_000.0)])

    def test_load_sec_companyfacts_prefers_annual_revenue_over_quarterly_tag_hit(self):
        class StubResp:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class StubHTTP:
            def get(self, url, headers=None):
                if url.endswith("company_tickers.json"):
                    return StubResp({"0": {"ticker": "ANNUAL", "cik_str": 123456}})
                return StubResp(
                    {
                        "facts": {
                            "us-gaap": {
                                "RevenueFromContractWithCustomerIncludingAssessedTax": {
                                    "units": {
                                        "USD": [
                                            {"end": "2026-03-31", "val": 3_000_000, "form": "10-Q", "fp": "Q1"}
                                        ]
                                    }
                                },
                                "Revenues": {
                                    "units": {
                                        "USD": [
                                            {"end": "2025-12-31", "val": 120_000_000, "form": "10-K", "fp": "FY"}
                                        ]
                                    }
                                },
                            }
                        }
                    }
                )

        facts = screener.load_sec_companyfacts(StubHTTP(), "ANNUAL")

        self.assertIsNotNone(facts)
        assert facts is not None
        self.assertEqual(facts.revenue, [("2025-12-31", 120_000_000.0)])

    def test_stage3_share_sanity_allows_low_implied_valuation(self):
        analysis = TickerAnalysis(
            symbol="LOWDCF",
            quote=QuoteSnapshot(symbol="LOWDCF", price=50.0, market_cap=5_000_000_000.0),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            sec=SECFacts(
                revenue=[("2023-12-31", 100_000_000.0), ("2024-12-31", 110_000_000.0)],
                op_cash_flow=[("2024-12-31", 5_000_000.0)],
                cash=[("2024-12-31", 10_000_000.0)],
                shares=[("2024-12-31", 100_000_000.0)],
            ),
        )

        stage3 = stage3_analysis(analysis)

        self.assertIsNotNone(stage3)
        assert stage3 is not None
        self.assertNotEqual(stage3.get("verdict"), "QC FAIL")
        self.assertIsNone(stage3["share_qc_detail"])
        self.assertLess(stage3["weighted_fair_value"] * 100_000_000.0, 5_000_000_000.0)

    def test_stage3_share_sanity_still_fails_high_implied_valuation(self):
        analysis = TickerAnalysis(
            symbol="HIGHDCF",
            quote=QuoteSnapshot(symbol="HIGHDCF", price=1.0, market_cap=100_000_000.0),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            sec=SECFacts(
                revenue=[("2023-12-31", 5_000_000_000.0), ("2024-12-31", 10_000_000_000.0)],
                op_cash_flow=[("2024-12-31", 1_000_000_000.0)],
                cash=[("2024-12-31", 100_000_000.0)],
                shares=[("2024-12-31", 100_000_000.0)],
            ),
        )

        stage3 = stage3_analysis(analysis)

        self.assertIsNotNone(stage3)
        assert stage3 is not None
        self.assertEqual(stage3["verdict"], "QC FAIL")
        self.assertIn("share denominator sanity failed", stage3["qc_fail_reason"])
        self.assertIn("implied $", stage3["share_qc_detail"])

    def test_summary_verdict_uses_only_legal_labels(self):
        stage1_only = TickerAnalysis(symbol="X", quote=QuoteSnapshot(symbol="X", price=25.0), barchart=BarchartSnapshot(), options=OptionsSnapshot(), stage1_pass=True)
        self.assertEqual(screener.summary_verdict(stage1_only), "NO ENTRY")

        qc_fail = TickerAnalysis(
            symbol="Y",
            quote=QuoteSnapshot(symbol="Y", price=25.0),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            stage1_pass=True,
            stage3={"verdict": "QC FAIL", "qc_fail_reason": "bad data", "category": None, "weighted_fair_value": None, "mos_threshold": None},
        )
        self.assertEqual(screener.summary_verdict(qc_fail), "QC FAIL")

    def test_sector_spread_groups_by_sector_and_unknown(self):
        analyses = [
            TickerAnalysis(symbol="A", quote=QuoteSnapshot(symbol="A", sector="Technology"), barchart=BarchartSnapshot(), options=OptionsSnapshot()),
            TickerAnalysis(symbol="B", quote=QuoteSnapshot(symbol="B", sector="Technology"), barchart=BarchartSnapshot(), options=OptionsSnapshot()),
            TickerAnalysis(symbol="C", quote=QuoteSnapshot(symbol="C", sector="Finance"), barchart=BarchartSnapshot(), options=OptionsSnapshot()),
            TickerAnalysis(symbol="D", quote=QuoteSnapshot(symbol="D"), barchart=BarchartSnapshot(), options=OptionsSnapshot()),
        ]

        self.assertEqual(sector_spread(analyses), [("Technology", 2), ("Finance", 1), ("Unknown", 1)])
    def test_stage2_report_defaults_to_named_output_and_includes_hp(self):
        analysis = TickerAnalysis(
            symbol="TEST",
            quote=QuoteSnapshot(symbol="TEST", price=25.0, market_cap=2e9, sector="Tech", industry="Software"),
            barchart=BarchartSnapshot(),
            options=OptionsSnapshot(),
            stage1_pass=True,
            stage1_reasons=["example reason"],
        )
        analysis.stage2_tests = [
            {"name": "iv spike diagnosis", "status": "WEAK", "detail": "mixed catalyst", "score": 0.5, "hp_loss": 1},
            {"name": "meme stock", "status": "PASS", "detail": "0-1 meme signals", "score": 1.0, "hp_loss": 0},
        ]
        analysis.stage2_hp_total = 10
        analysis.stage2_hp_left = 9
        analysis.stage2_score = 1.5
        analysis.stage2_verdict = "PASS"
        analysis.stage2_tier = "Diamond"
        analysis.eligible_for_stage3 = True
        row = stage2_report._report_row(
            {
                "symbol": "TEST",
                "name": "Test Co",
                "master_exchange": "NASDAQ",
                "sector": "Technology",
                "industry": "Software",
                "price_proxy": "25.0",
                "share_volume": "1000000",
                "market_cap": "2000000000",
                "one_yr_target": "30.0",
                "stage1_pass": "PASS",
                "stage1_reasons": "example reason",
            },
            analysis,
        )
        self.assertEqual(stage2_report._default_output_path("/tmp/run/Stage1_PASS.csv").endswith("Stage2_Report.csv"), True)
        self.assertEqual(row["stage2_hp_left"], 9)
        self.assertEqual(row["hp_tier"], "Diamond")
        self.assertEqual(row["eligible_for_stage3"], "TRUE")
        self.assertEqual(row["iv_spike_diagnosis_status"], "WEAK")
        self.assertEqual(row["iv_spike_diagnosis_hp_loss"], 1)
        self.assertEqual(row["meme_stock_status"], "PASS")
        self.assertEqual(row["meme_stock_hp_loss"], 0)


if __name__ == "__main__":
    unittest.main()
