from screener import BarchartSnapshot, OptionsSnapshot, QuoteSnapshot, TickerAnalysis
from stages.stage2.code.stage2_sieve import (
    AnalystConsensusTest,
    ChartPatternTest,
    InstitutionalOwnershipTest,
    IVSpikeDiagnosisTest,
    LiquidityTest,
    MemeStockTest,
    NewsSentimentTest,
    Stage2Sieve,
    hp_tier,
)


def analysis(**kwargs):
    quote = kwargs.pop("quote", QuoteSnapshot(symbol="TST", price=20.0))
    options = kwargs.pop("options", OptionsSnapshot())
    barchart = kwargs.pop("barchart", BarchartSnapshot(implied_volatility=90.0))
    return TickerAnalysis(symbol="TST", quote=quote, barchart=barchart, options=options, **kwargs)


def test_hp_tier_contract_uses_10_point_framework():
    assert hp_tier(10) == "Diamond"
    assert hp_tier(9) == "Diamond"
    assert hp_tier(8) == "Strong"
    assert hp_tier(7) == "Strong"
    assert hp_tier(6) == "Standard"
    assert hp_tier(5) == "Standard"
    assert hp_tier(4) == "Watch"
    assert hp_tier(3) == "Watch"
    assert hp_tier(2) == "Eliminated"
    assert hp_tier(0) == "Eliminated"


def test_stage2_sieve_runs_seven_separate_tests_and_preserves_stage1_pass():
    a = analysis(quote=QuoteSnapshot(symbol="TST", price=20.0, target_price=30.0, inst_own=75.0))
    a.stage1_pass = True
    a.options = OptionsSnapshot(total_volume=20_000, total_open_interest=30_000, atm_bid_ask_spread=0.05)

    Stage2Sieve().run(a, price_history=[18.0] * 230 + [20.0])

    assert [test["name"] for test in a.stage2_tests] == [
        "iv spike diagnosis",
        "meme stock",
        "chart pattern",
        "news sentiment",
        "analyst consensus",
        "liquidity",
        "institutional ownership",
    ]
    assert a.stage2_hp_total == 10
    assert a.stage2_hp_left == 10
    assert a.stage2_verdict == "PASS"
    assert a.stage2_tier == "Diamond"
    assert a.eligible_for_stage3 is True
    assert a.stage1_pass is True


def test_each_stage2_test_is_its_own_class_with_pass_weak_bad_damage():
    test_classes = [
        IVSpikeDiagnosisTest,
        MemeStockTest,
        ChartPatternTest,
        NewsSentimentTest,
        AnalystConsensusTest,
        LiquidityTest,
        InstitutionalOwnershipTest,
    ]
    assert all(hasattr(cls(), "run") for cls in test_classes)

    assert MemeStockTest().run(analysis()).status == "PASS"
    weak = analysis(quote=QuoteSnapshot(symbol="TST", price=20.0, inst_own=20.0, eps_next_y=1.0, news=[{"headline": "Retail squeeze returns"}]))
    assert MemeStockTest().run(weak).hp_loss == 1
    bad = analysis(quote=QuoteSnapshot(symbol="TST", price=20.0, inst_own=20.0, eps_next_y=-1.0, news=[{"headline": "Retail squeeze meme"}]))
    assert MemeStockTest().run(bad, price_history=[10.0] * 19 + [25.0]).hp_loss == 2


def test_liquidity_uses_stage2_thresholds_from_chat_contract():
    q = QuoteSnapshot(symbol="TST", price=20.0, market_cap=2_000_000_000)
    assert LiquidityTest().run(analysis(quote=q, options=OptionsSnapshot(atm_bid_ask_spread=0.09, total_volume=5_001, total_open_interest=10_001))).status == "PASS"
    assert LiquidityTest().run(analysis(quote=q, options=OptionsSnapshot(atm_bid_ask_spread=0.20, total_volume=2_000, total_open_interest=5_000))).status == "WEAK"
    assert LiquidityTest().run(analysis(quote=q, options=OptionsSnapshot(atm_bid_ask_spread=0.30, total_volume=1_001, total_open_interest=1_500))).status == "BAD"


def test_report_runner_import_path_exists_under_stage2_code():
    from stages.stage2.code.run_stage2 import DEFAULT_INPUT, DEFAULT_OUTPUT, DEFAULT_LOG_DIR

    assert str(DEFAULT_INPUT).endswith("stages/stage2/input/Stage1_PASS.csv")
    assert str(DEFAULT_OUTPUT).endswith("stages/stage2/output/Stage2_Report.csv")
    assert str(DEFAULT_LOG_DIR).endswith("stages/stage2/audit_logs")
