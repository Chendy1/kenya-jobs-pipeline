"""Phase 5: build the star schema (dw.*) from clean.*.

From the repo root with the venv active (run the transform first so clean.* is fresh):
    python -m src.warehouse.build
"""
from __future__ import annotations

import logging
from pathlib import Path

from src.storage.postgres import get_conn, init_schema

log = logging.getLogger(__name__)

LOAD_SQL = Path(__file__).resolve().parents[2] / "sql" / "loads" / "dw_load.sql"
TABLES = ["dim_date", "dim_location", "dim_company", "dim_skill",
          "fact_job_postings", "bridge_job_skill"]


def build() -> dict[str, int]:
    init_schema()  # applies sql/*.sql (all idempotent) so tables and views exist
    with get_conn() as conn:
        conn.execute(LOAD_SQL.read_text(encoding="utf-8"))  # one transaction
        counts = {t: conn.execute(f"SELECT count(*) FROM dw.{t}").fetchone()[0] for t in TABLES}
    for table, n in counts.items():
        log.info("dw.%-18s %8d rows", table, n)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build()