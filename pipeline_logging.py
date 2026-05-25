from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LOGGER_NAME = "market_funnel"


def configure_logging(*, level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Configure a shared logger for pipeline-style JSON events.

    Logs are emitted as one JSON object per line so drift across stages can be
    diffed, grepped, or shipped into downstream tooling without extra parsing.
    """

    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter("%(message)s")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": event,
        **fields,
    }
    logger.info(json.dumps(payload, sort_keys=True, default=str))
