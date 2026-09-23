"""Postgres connection, schema setup and idempotent loading of raw envelopes."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

load_dotenv()
log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

INSERT_SQL = """
INSERT INTO raw.job_postings (source, job_key, content_hash, scraped_at, run_id, payload)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source, job_key, content_hash) DO NOTHING
"""


def get_conn() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        dbname=os.getenv("POSTGRES_DB", "kenya_jobs"),
        user=os.getenv("POSTGRES_USER", "jobs_user"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


def init_schema() -> None:
    """Run every sql/*.sql file in order. All statements are IF NOT EXISTS."""
    with get_conn() as conn:
        for path in sorted(SQL_DIR.glob("*.sql")):
            log.info("Applying %s", path.name)
            conn.execute(path.read_text(encoding="utf-8"))


def load_envelopes(envelopes: list[dict], raw_key: str | None = None) -> int:
    """Insert envelopes; duplicates are skipped. Returns rows actually inserted."""
    if not envelopes:
        return 0
    rows = [
        (
            e["source"], e["job_key"], e["content_hash"],
            e["scraped_at"], e["run_id"], Jsonb(e["payload"]),
        )
        for e in envelopes
    ]
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(INSERT_SQL, rows)
        inserted = cur.rowcount
        cur.execute(
            """INSERT INTO raw.ingest_runs
               (run_id, source, raw_key, records_seen, records_inserted)
               VALUES (%s, %s, %s, %s, %s)""",
            (envelopes[0]["run_id"], envelopes[0]["source"], raw_key, len(rows), inserted),
        )
    log.info("Postgres: %d seen, %d new", len(rows), inserted)
    return inserted