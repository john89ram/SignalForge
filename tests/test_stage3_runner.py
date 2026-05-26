import csv
import json
from pathlib import Path

import pytest

from screener import QuoteSnapshot, SECFacts
from stages.stage3.code import run_stage3


def _write_stage2_csv(path: Path, rows):
    fieldnames = [
        "symbol",
        "sector",
        "hp_tier",
        "stage2_tier",
        "stage2_score",
        "stage2_hp_left",
        "stage2_verdict",
        "stage2_bad_text",
        "stage2_kills",
        "stage2_bad_count",
        "stage2_weak_text",
        "stage2_flags",
        "price_proxy",
        "one_yr_target",
        "eligible_for_stage3",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _base_row(symbol, tier="Diamond", score="5.0", eligible="TRUE", **extra):
    row = {
        "symbol": symbol,
        "sector": "Technology",
        "hp_tier": tier,
        "stage2_score": score,
        "stage2_hp_left": "10",
        "stage2_verdict": "PASS" if tier != "Eliminated" else "ELIMINATED",
        "stage2_bad_text": "",
        "stage2_bad_count": "0",
        "stage2_weak_text": "",
        "price_proxy": "20.00",
        "eligible_for_stage3": eligible,
    }
    row.update(extra)
    return row


def _stub_process(verdicts_seen):
    def fake(row, offline_input_only=False):
        symbol = row["symbol"]
        verdict = verdicts_seen[symbol]
        return {
            "symbol": symbol,
            "stage2_tier": run_stage3._get_tier(row),
            "stage2_score": row.get("stage2_score", ""),
            "stage2_hp_left": row.get("stage2_hp_left", ""),
            "stage3_verdict": verdict,
            "stage3_category": "A" if verdict != "QC FAIL" else "",
            "weighted_fair_value": "20",
            "mos_threshold": "16",
            "current_price": "10",
            "undervaluation_pct": "100",
            "bear_value": "10",
            "realistic_value": "20",
            "bull_value": "30",
            "qc_fail_reason": "" if verdict != "QC FAIL" else "stub fail",
            "share_count_source": "sec",
            "share_qc_detail": "",
            "watch_signal": "watch",
            "kill_signal": "",
            "stage2_kills": run_stage3._get_kills_text(row),
            "stage2_flags": run_stage3._get_flags_text(row),
            "sector": row.get("sector", ""),
            "iv_rank": "",
            "implied_vol": "",
        }
    return fake


def test_tier_cascade_stops_early(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("BBB", "Diamond"), _base_row("CCC", "Strong")]
    _write_stage2_csv(input_csv, rows)
    processed = []

    def fake(row, offline_input_only=False):
        processed.append(row["symbol"])
        return _stub_process({"AAA": "DIAMOND", "BBB": "ENTRY", "CCC": "ENTRY"})(row, offline_input_only)

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)
    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=2, workers=1, show_progress=False)

    assert processed == ["AAA", "BBB"]
    assert result.tiers_consumed == ["Diamond"]
    assert result.cascade_stopped_early is True


def test_tier_cascade_continues(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("BBB", "Strong")]
    _write_stage2_csv(input_csv, rows)
    processed = []

    def fake(row, offline_input_only=False):
        processed.append(row["symbol"])
        return _stub_process({"AAA": "NO ENTRY", "BBB": "ENTRY"})(row, offline_input_only)

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)
    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=2, workers=1, show_progress=False)

    assert processed == ["AAA", "BBB"]
    assert result.tiers_consumed == ["Diamond", "Strong"]
    assert result.cascade_stopped_early is False


def test_failed_analysis_isolation(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("BBB", "Diamond")]
    _write_stage2_csv(input_csv, rows)

    def fake(row, offline_input_only=False):
        if row["symbol"] == "AAA":
            raise RuntimeError("boom")
        return _stub_process({"BBB": "ENTRY"})(row, offline_input_only)

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)
    run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, show_progress=False)

    output_rows = list(csv.DictReader(output_csv.open(encoding="utf-8")))
    assert {row["symbol"]: row["stage3_verdict"] for row in output_rows} == {"AAA": "QC FAIL", "BBB": "ENTRY"}
    assert "boom" in next(row for row in output_rows if row["symbol"] == "AAA")["qc_fail_reason"]


def test_output_sort_order(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [
        _base_row("ZZZ", "Strong", "9.0"),
        _base_row("BBB", "Diamond", "5.0"),
        _base_row("AAA", "Diamond", "5.0"),
        _base_row("CCC", "Diamond", "7.0"),
    ]
    _write_stage2_csv(input_csv, rows)
    monkeypatch.setattr(run_stage3, "_process_stage3_row", _stub_process({r["symbol"]: "NO ENTRY" for r in rows}))

    run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, show_progress=False)

    assert [row["symbol"] for row in csv.DictReader(output_csv.open(encoding="utf-8"))] == ["CCC", "AAA", "BBB", "ZZZ"]


def test_stage2_kills_propagated(monkeypatch):
    class FakeResponse:
        text = "html"

    class FakeHTTP:
        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(run_stage3, "parse_finviz_quote", lambda html, symbol: QuoteSnapshot(symbol=symbol, price=10.0))
    monkeypatch.setattr(run_stage3, "load_sec_companyfacts", lambda http, symbol: SECFacts(cik="1"))
    row = _base_row("AAA", stage2_bad_text="bad one | bad two", stage2_bad_count="2")

    analysis = run_stage3._analysis_from_stage2_row(row, FakeHTTP())

    assert analysis.stage2_kills == ["bad one", "bad two"]


def test_current_stage2_column_aliases_are_supported():
    row = _base_row("AAA", hp_tier="Strong", stage2_bad_text="bad", stage2_weak_text="weak")

    assert run_stage3._get_tier(row) == "Strong"
    assert run_stage3._get_kills_text(row) == "bad"
    assert run_stage3._get_flags_text(row) == "weak"


def test_stage2_kills_alias_without_bad_count_is_trusted(monkeypatch):
    class FakeResponse:
        text = "html"

    class FakeHTTP:
        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(run_stage3, "parse_finviz_quote", lambda html, symbol: QuoteSnapshot(symbol=symbol, price=10.0))
    monkeypatch.setattr(run_stage3, "load_sec_companyfacts", lambda http, symbol: SECFacts(cik="1"))
    row = _base_row("AAA", stage2_bad_count="", stage2_kills="legacy bad one | legacy bad two")

    analysis = run_stage3._analysis_from_stage2_row(row, FakeHTTP())

    assert analysis.stage2_kills == ["legacy bad one", "legacy bad two"]


def test_min_verdicts_zero_processes_all_requested_tiers(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("BBB", "Strong"), _base_row("CCC", "Watch")]
    _write_stage2_csv(input_csv, rows)
    processed = []

    def fake(row, offline_input_only=False):
        processed.append(row["symbol"])
        return _stub_process({"AAA": "DIAMOND", "BBB": "ENTRY", "CCC": "NO ENTRY"})(row, offline_input_only)

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)
    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, tiers=["Diamond", "Strong", "Watch"], show_progress=False)

    assert processed == ["AAA", "BBB", "CCC"]
    assert result.tiers_consumed == ["Diamond", "Strong", "Watch"]


def test_stage3_analysis_none_becomes_qc_fail_row(monkeypatch):
    class FakeResponse:
        text = "html"

    class FakeHTTP:
        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(run_stage3, "HTTP", lambda timeout=10, retries=1: FakeHTTP())
    monkeypatch.setattr(run_stage3, "parse_finviz_quote", lambda html, symbol: QuoteSnapshot(symbol=symbol, price=10.0))
    monkeypatch.setattr(run_stage3, "load_sec_companyfacts", lambda http, symbol: SECFacts(cik="1", revenue=[("2025", 1.0)], shares=[("2025", 1.0)]))
    monkeypatch.setattr(run_stage3, "stage3_analysis", lambda analysis: None)

    row = _base_row("AAA")
    result = run_stage3._process_stage3_row(row)

    assert result["stage3_verdict"] == "QC FAIL"
    assert result["qc_fail_reason"] == "stage3_analysis returned None"


def test_eliminated_stage2_rows_are_skipped(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("DEAD", "Eliminated", eligible="FALSE")]
    _write_stage2_csv(input_csv, rows)
    processed = []

    def fake(row, offline_input_only=False):
        processed.append(row["symbol"])
        return _stub_process({"AAA": "NO ENTRY", "DEAD": "ENTRY"})(row, offline_input_only)

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)
    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, show_progress=False)

    assert processed == ["AAA"]
    assert result.symbols_processed == 1
    assert list(csv.DictReader(output_csv.open(encoding="utf-8")))[0]["symbol"] == "AAA"


def test_fair_value_target_misalignment_requires_software_patch(monkeypatch):
    class FakeResponse:
        text = "html"

    class FakeHTTP:
        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(run_stage3, "HTTP", lambda timeout=10, retries=1: FakeHTTP())
    monkeypatch.setattr(
        run_stage3,
        "parse_finviz_quote",
        lambda html, symbol: QuoteSnapshot(symbol=symbol, price=63.64, target_price=69.95),
    )
    monkeypatch.setattr(run_stage3, "load_sec_companyfacts", lambda http, symbol: SECFacts(cik="1"))
    monkeypatch.setattr(
        run_stage3,
        "stage3_analysis",
        lambda analysis: {
            "category": "B",
            "weighted_fair_value": 1.16,
            "mos_threshold": 0.58,
            "current_price": 63.64,
            "undervaluation_pct": -98.17,
        },
    )

    result = run_stage3._process_stage3_row(_base_row("IONQ", one_yr_target="65.00"))

    assert result["stage2_one_yr_target"] == 65.0
    assert result["finviz_target_price"] == 69.95
    assert result["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert result["software_patch_required"] == "TRUE"
    assert "Stage 3 FV $1.16" in result["fair_value_target_gap_detail"]
    assert "Stage 2 target $65.00" in result["fair_value_target_gap_detail"]
    assert "Finviz target $69.95" in result["fair_value_target_gap_detail"]


def test_target_misalignment_is_written_to_csv_log_and_jsonl(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("MARA", "Diamond", one_yr_target="15.50")]
    _write_stage2_csv(input_csv, rows)

    def fake(row, offline_input_only=False):
        return {
            **_stub_process({"MARA": "NO ENTRY"})(row, offline_input_only),
            "weighted_fair_value": 0.26,
            "stage2_one_yr_target": 15.5,
            "finviz_target_price": 17.78,
            "target_benchmark_price": 15.5,
            "fair_value_target_gap_pct": -98.32,
            "fair_value_target_alignment": "SEVERE_MISALIGNMENT",
            "software_patch_required": "TRUE",
            "fair_value_target_gap_detail": "Stage 3 FV $0.26 is -98.3% below Stage 2 target $15.50; patch required",
        }

    monkeypatch.setattr(run_stage3, "_process_stage3_row", fake)

    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, show_progress=False)

    [output_row] = list(csv.DictReader(output_csv.open(encoding="utf-8")))
    assert output_row["software_patch_required"] == "TRUE"
    assert output_row["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert output_row["stage2_one_yr_target"] == "15.5"
    log_text = Path(result.log_path).read_text(encoding="utf-8")
    assert "software_patch_required=TRUE" in log_text
    assert "fv_target_alignment=SEVERE_MISALIGNMENT" in log_text
    symbol_events = [
        json.loads(line)
        for line in Path(result.audit_jsonl_path).read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "stage3_symbol_result"
    ]
    assert symbol_events[0]["software_patch_required"] == "TRUE"
    assert symbol_events[0]["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"


def test_audit_jsonl_contains_all_event_types(tmp_path, monkeypatch):
    input_csv = tmp_path / "Stage2_Report.csv"
    output_csv = tmp_path / "Stage3_Report.csv"
    rows = [_base_row("AAA", "Diamond"), _base_row("BBB", "Strong")]
    _write_stage2_csv(input_csv, rows)
    monkeypatch.setattr(run_stage3, "_process_stage3_row", _stub_process({"AAA": "NO ENTRY", "BBB": "ENTRY"}))

    result = run_stage3.run(input_csv, output_csv_path=output_csv, log_dir=tmp_path, min_verdicts=0, workers=1, show_progress=False)

    events = [json.loads(line) for line in Path(result.audit_jsonl_path).read_text(encoding="utf-8").splitlines()]
    event_types = [event["event"] for event in events]
    assert "stage3_run_start" in event_types
    assert event_types.count("stage3_symbol_result") == 2
    assert event_types.count("stage3_cascade_decision") == 2
    assert "stage3_run_complete" in event_types
