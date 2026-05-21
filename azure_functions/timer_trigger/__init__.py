"""Azure Functions timer trigger entrypoint.

Phase 5 deliverable: the same `main.run()` orchestrator wrapped for serverless
execution. Cron is configured in `function.json` — separate cadence for federal
(monthly) vs Florida (quarterly) is wired up by deploying two functions that
each pass a different --only list via environment variable.
"""
from __future__ import annotations

import json
import logging
import os

import azure.functions as func  # type: ignore[import-not-found]

from main import run

log = logging.getLogger(__name__)


def main(timer: "func.TimerRequest") -> None:
    only_env = os.environ.get("BRAIN_SOURCES")  # comma-separated, optional
    only = [k.strip() for k in only_env.split(",")] if only_env else None
    promote = os.environ.get("BRAIN_PROMOTE", "false").lower() == "true"
    summary = run(only=only, promote=promote)
    log.info("Brain run complete: %s", json.dumps(summary))
