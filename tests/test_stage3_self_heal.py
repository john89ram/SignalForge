import csv
import json
from pathlib import Path

from stages.stage3.code import stage3_self_heal


def _write_stage3_report(path: Path, rows):
    fieldnames = [
        "symbol",
        "stage2_tier",
        "stage3_verdict",
        "weighted_fair_value",
        "stage2_one_yr_target",
        "finviz_target_price",
        "fair_value_target_gap_pct",
        "fair_value_target_alignment",
        "software_patch_required",
        "fair_value_target_gap_detail",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def test_stage3_self_heal_invokes_hermes_for_patch_required_rows(tmp_path):
    report_csv = tmp_path / "Stage3_Report.csv"
    log_dir = tmp_path / "audit_logs"
    _write_stage3_report(
        report_csv,
        [
            {
                "symbol": "MARA",
                "stage2_tier": "Diamond",
                "stage3_verdict": "NO ENTRY",
                "weighted_fair_value": "0.26",
                "stage2_one_yr_target": "15.5",
                "finviz_target_price": "17.78",
                "fair_value_target_gap_pct": "-98.32",
                "fair_value_target_alignment": "SEVERE_MISALIGNMENT",
                "software_patch_required": "TRUE",
                "fair_value_target_gap_detail": "Stage 3 FV $0.26 is -98.3% below target; patch required",
            },
            {
                "symbol": "IONQ",
                "stage2_tier": "Diamond",
                "stage3_verdict": "NO ENTRY",
                "software_patch_required": "FALSE",
            },
        ],
    )
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return stage3_self_heal.CommandResult(returncode=0, stdout="agent ok", stderr="")

    result = stage3_self_heal.run(report_csv_path=report_csv, log_dir=log_dir, command_runner=fake_runner)

    assert result.software_patch_required_count == 1
    assert result.symbols == ["MARA"]
    assert result.hermes_invoked is True
    assert result.returncode == 0
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[:3] == ["hermes", "chat", "-q"]
    prompt = cmd[3]
    assert str(report_csv.resolve()) in prompt
    assert "MARA" in prompt
    assert "software_patch_required = TRUE" in prompt
    assert "patch only if warranted" in prompt
    assert "Do not overwrite OG Stage 3 code" in prompt
    assert "stages/stage3/code/patches/" in prompt
    assert "<original_stem>__patched_<trigger_id>.py" in prompt
    assert "<original_stem>__og_<trigger_id>.py" in prompt
    assert kwargs["cwd"] == str(stage3_self_heal.REPO_ROOT)

    log_text = Path(result.log_path).read_text(encoding="utf-8")
    assert "stage3_self_heal started" in log_text
    assert "patch_required_symbols=MARA" in log_text
    assert "hermes_invoked=True" in log_text
    assert "returncode=0" in log_text

    events = [json.loads(line) for line in Path(result.audit_jsonl_path).read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == [
        "stage3_self_heal_start",
        "stage3_self_heal_patch_rows_detected",
        "stage3_self_heal_hermes_invocation",
        "stage3_self_heal_complete",
    ]
    assert events[1]["symbols"] == ["MARA"]
    assert events[2]["command"][:3] == ["hermes", "chat", "-q"]


def test_stage3_self_heal_noops_and_logs_when_no_patch_required_rows(tmp_path):
    report_csv = tmp_path / "Stage3_Report.csv"
    log_dir = tmp_path / "audit_logs"
    _write_stage3_report(
        report_csv,
        [{"symbol": "IONQ", "stage3_verdict": "NO ENTRY", "software_patch_required": "FALSE"}],
    )
    calls = []

    result = stage3_self_heal.run(
        report_csv_path=report_csv,
        log_dir=log_dir,
        command_runner=lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    assert result.software_patch_required_count == 0
    assert result.symbols == []
    assert result.hermes_invoked is False
    assert result.returncode is None
    assert calls == []
    log_text = Path(result.log_path).read_text(encoding="utf-8")
    assert "no software_patch_required rows found" in log_text
    events = [json.loads(line) for line in Path(result.audit_jsonl_path).read_text(encoding="utf-8").splitlines()]
    assert events[-1]["hermes_invoked"] is False


def test_stage3_self_heal_dry_run_builds_prompt_without_invoking_hermes(tmp_path):
    report_csv = tmp_path / "Stage3_Report.csv"
    log_dir = tmp_path / "audit_logs"
    _write_stage3_report(report_csv, [{"symbol": "RGTI", "software_patch_required": "TRUE"}])
    calls = []

    result = stage3_self_heal.run(
        report_csv_path=report_csv,
        log_dir=log_dir,
        dry_run=True,
        command_runner=lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    assert result.software_patch_required_count == 1
    assert result.symbols == ["RGTI"]
    assert result.hermes_invoked is False
    assert result.prompt_path
    assert "RGTI" in Path(result.prompt_path).read_text(encoding="utf-8")
    assert calls == []
