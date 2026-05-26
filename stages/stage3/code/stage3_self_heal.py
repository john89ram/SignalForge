"""Option A self-healing trigger for Stage 3 software-patch flags.

Reads Stage3_Report.csv, detects rows with software_patch_required=TRUE, and
invokes `hermes chat -q <prompt>` with a compact remediation prompt. The script
records both human-readable and JSONL audit logs so operator handoff is explicit.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT = REPO_ROOT / "stages" / "stage3" / "output" / "Stage3_Report.csv"
DEFAULT_LOG_DIR = REPO_ROOT / "stages" / "stage3" / "audit_logs"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class Stage3SelfHealResult:
    report_csv_path: str
    log_path: str
    audit_jsonl_path: str
    prompt_path: Optional[str]
    software_patch_required_count: int
    symbols: List[str]
    hermes_invoked: bool
    returncode: Optional[int]
    elapsed_seconds: float


CommandRunner = Callable[[List[str]], CommandResult]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _is_true(value: Any) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "1", "YES", "Y"}


def _read_patch_rows(report_csv_path: Path) -> List[Dict[str, str]]:
    with report_csv_path.open("r", encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh) if _is_true(row.get("software_patch_required"))]


def _compact_row(row: Dict[str, str]) -> Dict[str, str]:
    wanted = [
        "symbol",
        "stage2_tier",
        "stage3_verdict",
        "stage3_category",
        "weighted_fair_value",
        "stage2_one_yr_target",
        "finviz_target_price",
        "target_benchmark_price",
        "fair_value_target_gap_pct",
        "fair_value_target_alignment",
        "fair_value_target_gap_detail",
        "qc_fail_reason",
        "share_count_source",
        "share_qc_detail",
        "sector",
    ]
    return {key: row.get(key, "") for key in wanted if row.get(key, "") not in (None, "")}


def build_prompt(report_csv_path: Path, patch_rows: Sequence[Dict[str, str]]) -> str:
    symbols = [row.get("symbol", "").strip().upper() for row in patch_rows if row.get("symbol")]
    compact_rows = [_compact_row(row) for row in patch_rows]
    rows_json = json.dumps(compact_rows, indent=2, sort_keys=True)
    symbol_list = ", ".join(symbols)
    return f"""Stage 3 detected software_patch_required = TRUE rows in SignalForge.

Repository: {REPO_ROOT}
Report CSV: {report_csv_path.resolve()}
Affected symbols: {symbol_list}

Compact row evidence:
{rows_json}

Remediation instructions:
- Inspect Stage 3 source data and code before changing anything.
- Classify each issue as SOURCE_BUG, MODEL_FAMILY_MISSING, DATA_PROVIDER_ISSUE, SHARE_DENOMINATOR_BUG, TARGET_OUTLIER, or NO_PATCH_SAFE.
- patch only if warranted by a confirmed software/model gap; do not force valuations to match targets.
- Do not overwrite OG Stage 3 code during self-heal remediation.
- Use this non-overwrite naming scheme for every code patch:
  - Define trigger_id as the current UTC timestamp plus the affected-symbol slug, e.g. 20260526T031500Z_MARA_QUBT.
  - Create a patch bundle directory: stages/stage3/code/patches/<trigger_id>/.
  - Copy the original file before edits to: stages/stage3/code/patches/<trigger_id>/original/<original_stem>__og_<trigger_id>.py.
  - Save the patched code as a new file named: stages/stage3/code/patches/<trigger_id>/patched/<original_stem>__patched_<trigger_id>.py.
  - Leave the original production file unchanged unless Jonathan explicitly promotes the patch later.
  - Record the OG path, patched path, trigger_id, and symbol list in the audit handoff.
- Prefer branch-based or minimal code edits for material model changes, but keep the actual patched code in the patch bundle above.
- Add or update regression tests for any code change; tests may import the patched module path directly.
- Run focused tests and rerun Stage 3 enough to verify the software_patch_required rows changed appropriately or are documented as non-code issues.
- Write audit logs / handoff notes under stages/stage3/audit_logs/.
- Commit and push safe patch-bundle artifacts, then report exactly what changed and what remains human-reviewed.
"""


def _default_runner(cmd: List[str], **kwargs: Any) -> CommandResult:
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False, **kwargs)
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def _write_jsonl(path: Path, events: Sequence[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def run(
    report_csv_path: Path | str = DEFAULT_REPORT,
    *,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    hermes_bin: str = "hermes",
    dry_run: bool = False,
    command_runner: Optional[Callable[..., CommandResult]] = None,
) -> Stage3SelfHealResult:
    start = time.perf_counter()
    report_path = Path(report_csv_path).expanduser().resolve()
    log_root = Path(log_dir).expanduser().resolve()
    log_root.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    log_path = log_root / f"stage3_self_heal_{ts}.log"
    audit_jsonl_path = log_root / f"stage3_self_heal_{ts}.jsonl"
    prompt_path = log_root / f"stage3_self_heal_prompt_{ts}.md"

    events: List[Dict[str, Any]] = []
    log_lines = [
        f"stage3_self_heal started {ts}",
        f"report_csv={report_path}",
        f"log={log_path}",
        f"audit_jsonl={audit_jsonl_path}",
        f"dry_run={dry_run}",
    ]
    events.append(
        {
            "event": "stage3_self_heal_start",
            "timestamp": ts,
            "report_csv": str(report_path),
            "dry_run": dry_run,
        }
    )

    patch_rows = _read_patch_rows(report_path)
    symbols = [row.get("symbol", "").strip().upper() for row in patch_rows if row.get("symbol")]
    log_lines.append(f"software_patch_required_count={len(patch_rows)}")
    log_lines.append(f"patch_required_symbols={','.join(symbols)}")
    events.append(
        {
            "event": "stage3_self_heal_patch_rows_detected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": len(patch_rows),
            "symbols": symbols,
            "rows": [_compact_row(row) for row in patch_rows],
        }
    )

    hermes_invoked = False
    returncode: Optional[int] = None
    prompt_path_str: Optional[str] = None

    if not patch_rows:
        log_lines.append("no software_patch_required rows found")
    else:
        prompt = build_prompt(report_path, patch_rows)
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_path_str = str(prompt_path)
        log_lines.append(f"prompt_path={prompt_path}")
        cmd = [hermes_bin, "chat", "-q", prompt]
        if dry_run:
            log_lines.append("dry_run=True; hermes invocation skipped")
        else:
            runner = command_runner or _default_runner
            hermes_invoked = True
            command_result = runner(cmd, cwd=str(REPO_ROOT))
            returncode = command_result.returncode
            log_lines.extend(
                [
                    "hermes_invoked=True",
                    f"command={json.dumps(cmd[:3] + ['<prompt>'])}",
                    f"returncode={returncode}",
                    "stdout_begin",
                    command_result.stdout.rstrip(),
                    "stdout_end",
                    "stderr_begin",
                    command_result.stderr.rstrip(),
                    "stderr_end",
                ]
            )
            events.append(
                {
                    "event": "stage3_self_heal_hermes_invocation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": cmd,
                    "cwd": str(REPO_ROOT),
                    "returncode": returncode,
                    "stdout": command_result.stdout,
                    "stderr": command_result.stderr,
                }
            )

    if not hermes_invoked:
        log_lines.append("hermes_invoked=False")

    elapsed = round(time.perf_counter() - start, 3)
    complete = {
        "event": "stage3_self_heal_complete",
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "software_patch_required_count": len(patch_rows),
        "symbols": symbols,
        "hermes_invoked": hermes_invoked,
        "returncode": returncode,
        "runtime_seconds": elapsed,
        "prompt_path": prompt_path_str,
        "log_path": str(log_path),
        "audit_jsonl_path": str(audit_jsonl_path),
    }
    events.append(complete)
    log_lines.append("summary=" + json.dumps(complete, sort_keys=True))
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    _write_jsonl(audit_jsonl_path, events)

    return Stage3SelfHealResult(
        report_csv_path=str(report_path),
        log_path=str(log_path),
        audit_jsonl_path=str(audit_jsonl_path),
        prompt_path=prompt_path_str,
        software_patch_required_count=len(patch_rows),
        symbols=symbols,
        hermes_invoked=hermes_invoked,
        returncode=returncode,
        elapsed_seconds=elapsed,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Invoke Hermes when Stage 3 flags software_patch_required rows")
    parser.add_argument("--report-csv", default=str(DEFAULT_REPORT), help="Path to Stage3_Report.csv")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Directory for self-heal audit logs")
    parser.add_argument("--hermes-bin", default="hermes", help="Hermes executable to invoke")
    parser.add_argument("--dry-run", action="store_true", help="Write prompt/logs but do not invoke Hermes")
    args = parser.parse_args(argv)
    result = run(
        args.report_csv,
        log_dir=args.log_dir,
        hermes_bin=args.hermes_bin,
        dry_run=args.dry_run,
    )
    print("Stage 3 self-heal check complete")
    print(f"- Patch-required rows: {result.software_patch_required_count}")
    print(f"- Symbols: {', '.join(result.symbols) if result.symbols else 'none'}")
    print(f"- Hermes invoked: {result.hermes_invoked}")
    print(f"- Log: {result.log_path}")
    print(f"- Audit JSONL: {result.audit_jsonl_path}")
    if result.prompt_path:
        print(f"- Prompt: {result.prompt_path}")
    return 0 if result.returncode in (None, 0) else int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
