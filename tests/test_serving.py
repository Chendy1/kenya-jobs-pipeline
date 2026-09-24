import os

import psycopg
import pytest

from src.storage.postgres import get_conn, init_schema


@pytest.fixture(scope="module")
def db():
    try:
        init_schema()
    except Exception as exc:  # no database running: skip instead of failing
        pytest.skip(f"Postgres not available: {exc}")


@pytest.mark.parametrize("title,industry,expected", [
    ("Senior Data Engineer", None, "Data & Analytics"),
    ("Data Entry Clerk", None, "Admin & Support"),
    ("Sales Accounts Executive", None, "Sales & Marketing"),
    ("Chief Accountant – Hospitality Operations", None, "Finance & Accounting"),
    ("Executive Chef", None, "Hospitality & Tourism"),
    ("Fleet Manager - Akuka Cabs", None, "Logistics & Supply Chain"),
    ("Social Media Manager — NovaFleet", None, "Sales & Marketing"),
    ("Senior Infrastructure & Cybersecurity Engineer", None, "Software & IT"),
    ("Senior Salesforce Developer (on-site Kenya)", None, "Software & IT"),
    ("Registered Nurse", None, "Health & Medical"),
    ("Primary School Teacher", None, "Education & Training"),
    ("Programme Officer", None, "NGO & Development"),
    ("Mechanical Engineer", None, "Engineering & Construction"),
    ("Real Estate Sales Manager", None, "Sales & Marketing"),
    ("Virtual Executive Assistant", None, "Admin & Support"),
    ("Coordinator", "ICT / Computer", "Software & IT"),        # industry is the fallback
    ("Sales Executive", "ICT / Computer", "Sales & Marketing"),  # a title match beats the industry
    ("Wanderer of Realms", None, "Other"),
])
def test_category_rules(db, title, industry, expected):
    with get_conn() as conn:
        got = conn.execute("SELECT ref.classify_category(%s, %s)", (title, industry)).fetchone()[0]
    assert got == expected


def test_public_view_respects_the_publishing_policy(db):
    with get_conn() as conn:
        blocked = conn.execute(
            "SELECT count(*) FROM dw.v_public_jobs p JOIN ref.source_publishing sp USING (source) "
            "WHERE NOT sp.publishable").fetchone()[0]
        unlisted = conn.execute(
            "SELECT count(*) FROM dw.v_public_jobs p LEFT JOIN ref.source_publishing sp USING (source) "
            "WHERE sp.source IS NULL").fetchone()[0]
        dupes = conn.execute(
            "SELECT count(*) FROM dw.v_public_jobs v JOIN dw.fact_job_postings f USING (job_posting_key) "
            "WHERE f.is_duplicate").fetchone()[0]
    assert blocked == 0 and unlisted == 0 and dupes == 0


def test_public_views_carry_no_descriptions(db):
    with get_conn() as conn:
        cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'dw' AND table_name = 'v_public_jobs'").fetchall()]
    assert cols and not any("description" in c for c in cols)


def test_reader_role_is_least_privilege(db):
    password = os.getenv("APP_DB_PASSWORD")
    if not password:
        pytest.skip("APP_DB_PASSWORD not set")
    from src.serving.setup_reader import setup

    user = setup()
    conn = psycopg.connect(host=os.getenv("POSTGRES_HOST", "localhost"),
                           port=int(os.getenv("POSTGRES_PORT", "5433")),
                           dbname=os.getenv("POSTGRES_DB", "kenya_jobs"), user=user, password=password)
    try:
        conn.execute("SELECT count(*) FROM dw.v_public_jobs")
        conn.rollback()
        for table in ("raw.job_postings", "clean.job_postings", "dw.fact_job_postings", "dw.v_jobs_enriched"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
            conn.rollback()
    finally:
        conn.close()