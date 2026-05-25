#!/usr/bin/env python3
"""Backward-compatible wrapper for Stage 1 / Step 5 complete output.

The canonical module is `stages.stage1.code.step5_complete_stage1_output`.
This wrapper remains so older imports and commands keep working while docs and
new code use the Step 5 name consistently.
"""

from __future__ import annotations

from stages.stage1.code.step5_complete_stage1_output import (  # noqa: F401
    Stage1Step5Result,
    build_parser,
    main,
    run_stage1_step5_complete_output,
)

Stage1Step4Result = Stage1Step5Result
run_stage1_step4_complete_output = run_stage1_step5_complete_output

if __name__ == "__main__":
    raise SystemExit(main())
