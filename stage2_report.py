#!/usr/bin/env python3
"""Backward-compatible entry point for the canonical Stage 2 runner.

The implementation now lives under `stages/stage2/code/` so Stage 2 code is
co-located with the stage artifacts. This module keeps older imports and CLI
calls working.
"""

from __future__ import annotations

from pathlib import Path

from stages.stage2.code.run_stage2 import _report_row, main, run

DEFAULT_INPUT_NAME = "Stage1_PASS.csv"
DEFAULT_OUTPUT_NAME = "Stage2_Report.csv"


def _default_output_path(input_csv: str) -> str:
    return str(Path(input_csv).expanduser().with_name(DEFAULT_OUTPUT_NAME))


if __name__ == "__main__":
    raise SystemExit(main())
