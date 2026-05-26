import importlib.util
import sys
from pathlib import Path


PATCHED_RUNNER = Path(
    "stages/stage3/code/patches/20260526T032041Z_MARA_PCT_QUBT_PLUS42/"
    "patched/run_stage3__patched_20260526T032041Z_MARA_PCT_QUBT_PLUS42.py"
)


def _load_patched_runner():
    spec = importlib.util.spec_from_file_location("stage3_patch_20260526T032041Z", PATCHED_RUNNER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_patched_target_alignment_keeps_severe_gap_but_does_not_force_patch_for_model_family_gap():
    runner = _load_patched_runner()

    alignment = runner._target_alignment(
        1.16,
        65.0,
        69.95,
        current_price=63.64,
        stage3_category="B",
        stage3_verdict="NO ENTRY",
        sector="Technology",
        share_count_source="sec",
        share_qc_detail=None,
    )

    assert alignment["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert alignment["software_patch_required"] == "FALSE"
    assert "remediation classification MODEL_FAMILY_MISSING" in alignment["fair_value_target_gap_detail"]
    assert "no automated software patch safe from target gap alone" in alignment["fair_value_target_gap_detail"]


def test_patched_target_alignment_classifies_market_cap_implied_rows_as_data_provider_issue():
    runner = _load_patched_runner()

    alignment = runner._target_alignment(
        -68.41,
        42.5,
        41.44,
        current_price=28.65,
        stage3_category="B",
        stage3_verdict="NO ENTRY",
        sector="Finance",
        share_count_source="market_cap_implied",
        share_qc_detail=None,
    )

    assert alignment["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert alignment["software_patch_required"] == "FALSE"
    assert "remediation classification DATA_PROVIDER_ISSUE" in alignment["fair_value_target_gap_detail"]


def test_patched_target_alignment_still_escalates_confirmed_share_denominator_bug():
    runner = _load_patched_runner()

    alignment = runner._target_alignment(
        300.0,
        15.0,
        15.5,
        current_price=14.0,
        stage3_category="A",
        stage3_verdict="ENTRY",
        sector="Technology",
        share_count_source="sec",
        share_qc_detail="SEC shares disagree with market-cap-implied shares",
    )

    assert alignment["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert alignment["software_patch_required"] == "TRUE"
    assert "remediation classification SHARE_DENOMINATOR_BUG" in alignment["fair_value_target_gap_detail"]


def test_patched_target_alignment_classifies_far_external_target_as_target_outlier():
    runner = _load_patched_runner()

    alignment = runner._target_alignment(
        1.04,
        21.5,
        24.0,
        current_price=13.53,
        stage3_category="B",
        stage3_verdict="NO ENTRY",
        sector="Health Care",
        share_count_source="sec",
        share_qc_detail=None,
    )

    assert alignment["fair_value_target_alignment"] == "SEVERE_MISALIGNMENT"
    assert alignment["software_patch_required"] == "FALSE"
    assert "remediation classification TARGET_OUTLIER" in alignment["fair_value_target_gap_detail"]
