"""Database access for the app. Public mode = read-only role; private mode = owner login."""
from __future__ import annotations

import os

import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()


def mode() -> str:
    return "private" if os.getenv("APP_MODE", "public").lower() == "private" else "public"


def _connect() -> psycopg.Connection:
    common = dict(host=os.getenv("POSTGRES_HOST", "localhost"),
                  port=int(os.getenv("POSTGRES_PORT", "5433")),
                  dbname=os.getenv("POSTGRES_DB", "kenya_jobs"))
    if mode() == "private":
        return psycopg.connect(user=os.getenv("POSTGRES_USER", "jobs_user"),
                               password=os.environ["POSTGRES_PASSWORD"], **common)
    password = os.environ.get("APP_DB_PASSWORD")
    if not password:
        raise RuntimeError("APP_DB_PASSWORD is not set. Set it in .env, then run: "
                           "python -m src.serving.setup_reader")
    return psycopg.connect(user=os.getenv("APP_DB_USER", "app_reader"), password=password, **common)


def query_df(sql: str, params=None) -> pd.DataFrame:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [c.name for c in cur.description]
    return pd.DataFrame(rows, columns=columns)