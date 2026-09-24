"""Record each pipeline run in ops.pipeline_runs."""
from __future__ import annotations

import logging
from datetime import datetime

from psycopg.types.json import Jsonb

from src.storage.postgres import get_conn

log = logging.getLogger(__name__)


def record_run(started: datetime, finished: datetime, status: str, summary: dict) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO ops.pipeline_runs (started_at, finished_at, status, summary) "
                "VALUES (%s, %s, %s, %s)", (started, finished, status, Jsonb(summary)))
    except Exception:
        log.exception("could not record pipeline run")