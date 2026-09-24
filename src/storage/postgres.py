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
SIGHTING_SQL = """
INSERT INTO raw.sightings (source, job_key, seen_on, fetched)
VALUES (%s, %s, (now() AT TIME ZONE 'Africa/Nairobi')::date, %s)
ON CONFLICT (source, job_key, seen_on)
DO UPDATE SET fetched = raw.sightings.fetched OR EXCLUDED.fetched
"""


def record_sightings(source: str, seen_keys: set[str], fetched_keys: set[str]) -> int:
    """Log that these postings were seen today. Idempotent within a day."""
    keys = set(seen_keys) | set(fetched_keys)
    if not keys:
        return 0
    rows = [(source, k, k in fetched_keys) for k in sorted(keys)]
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(SIGHTING_SQL, rows)
    return len(rows)


def fresh_keys(source: str, days: int) -> set[str]:
    """Postings whose full page we downloaded within the last `days` days."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT job_key FROM raw.sightings "
            "WHERE source = %s AND fetched "
            "AND seen_on >= (now() AT TIME ZONE 'Africa/Nairobi')::date - %s",
            (source, days),
        ).fetchall()
    return {r[0] for r in rows}