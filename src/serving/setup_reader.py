"""Create the read-only database role the public app uses.

    python -m src.serving.setup_reader
Safe to re-run; run it again after adding new public views or changing the password.
"""
from __future__ import annotations

import os

from psycopg import sql

from src.storage.postgres import get_conn, init_schema


READER_VIEWS = [
    "dw.v_public_jobs",
    "ops.v_public_dq_summary",
    "ops.v_public_runs",
    "ops.v_public_source_freshness",
    # analytics: aggregates only (the base view v_analytics_base is deliberately NOT granted)
    "dw.v_coverage_overall",
    "dw.v_coverage_sources",
    "dw.v_skill_demand",
    "dw.v_county_summary",
    "dw.v_weekly_new_postings",
    "dw.v_advertised_window_stats",
    "dw.v_feed_depth",
    "dw.v_lifetime_km",
    "dw.v_lifetime_summary",
]

def setup() -> str:
    user = os.getenv("APP_DB_USER", "app_reader")
    password = os.environ.get("APP_DB_PASSWORD")
    if not password:
        raise SystemExit("Set APP_DB_PASSWORD in .env first (letters, digits and hyphens).")
    init_schema()  # makes sure the views exist
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
        conn.execute(sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
            sql.SQL("ALTER" if exists else "CREATE"), sql.Identifier(user), sql.Literal(password)))
        # belt and braces: read-only sessions and a statement timeout, on top of SELECT-only grants
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(user)))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'").format(sql.Identifier(user)))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA dw, ops TO {}").format(sql.Identifier(user)))
        for view in READER_VIEWS:
            schema, name = view.split(".")
            conn.execute(sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                sql.Identifier(schema), sql.Identifier(name), sql.Identifier(user)))
    return user


if __name__ == "__main__":
    role = setup()
    print(f"Role '{role}' is ready. It can SELECT only: {', '.join(READER_VIEWS)}")