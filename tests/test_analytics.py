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


def scalar(sql: str):
    with get_conn() as conn:
        return conn.execute(sql).fetchone()[0]


def test_wilson_interval_matches_hand_calculation(db):
    assert float(scalar("SELECT dw.wilson_low(5, 10)")) == pytest.approx(0.2366, abs=1e-3)
    assert float(scalar("SELECT dw.wilson_high(5, 10)")) == pytest.approx(0.7634, abs=1e-3)
    assert float(scalar("SELECT dw.wilson_low(0, 10)")) == pytest.approx(0.0, abs=1e-9)
    assert float(scalar("SELECT dw.wilson_high(0, 10)")) == pytest.approx(0.2775, abs=1e-3)
    assert scalar("SELECT dw.wilson_low(1, 0)") is None


def test_kaplan_meier_matches_textbook_example(db):
    # durations 1,2,2,3,4,5 with events T,T,F,T,F,T
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t, at_risk, n_events, survival FROM dw.km_survival("
            "ARRAY[1,2,2,3,4,5], ARRAY[true,true,false,true,false,true]) ORDER BY t").fetchall()
    got = {t: (at_risk, events, float(s)) for t, at_risk, events, s in rows}
    assert got[1][:2] == (6, 1) and got[1][2] == pytest.approx(5 / 6, abs=1e-3)
    assert got[2][:2] == (5, 1) and got[2][2] == pytest.approx(2 / 3, abs=1e-3)
    assert got[3][:2] == (3, 1) and got[3][2] == pytest.approx(4 / 9, abs=1e-3)
    assert got[4][:2] == (2, 0) and got[4][2] == pytest.approx(4 / 9, abs=1e-3)  # censored: no drop
    assert got[5][:2] == (1, 1) and got[5][2] == pytest.approx(0.0, abs=1e-6)


def test_analytics_use_publishable_sources_only(db):
    bad = scalar("SELECT count(*) FROM dw.v_analytics_base b JOIN ref.source_publishing sp USING (source) "
                 "WHERE NOT sp.publishable")
    assert bad == 0


def test_skill_demand_invariants(db):
    bad = scalar("SELECT count(*) FROM dw.v_skill_demand WHERE NOT (ci_low_pct <= pooled_pct "
                 "AND pooled_pct <= ci_high_pct AND postings <= n_tech "
                 "AND pooled_pct BETWEEN 0 AND 100 AND balanced_pct BETWEEN 0 AND 100)")
    assert bad == 0


def test_county_postings_add_up_to_the_denominator(db):
    with get_conn() as conn:
        total, n_located = conn.execute(
            "SELECT COALESCE(sum(postings), 0), COALESCE(max(n_located), 0) FROM dw.v_county_summary").fetchone()
    assert total == n_located


def test_coverage_totals_agree(db):
    assert scalar("SELECT postings FROM dw.v_coverage_overall") == \
        scalar("SELECT COALESCE(sum(postings), 0) FROM dw.v_coverage_sources")


def test_survival_curves_never_increase(db):
    bad = scalar("SELECT count(*) FROM (SELECT survival, lag(survival) OVER "
                 "(PARTITION BY source ORDER BY age_days) AS prev FROM dw.v_lifetime_km) t "
                 "WHERE prev IS NOT NULL AND survival > prev")
    assert bad == 0


def test_reader_sees_only_the_aggregate_views(db):
    password = os.getenv("APP_DB_PASSWORD")
    if not password:
        pytest.skip("APP_DB_PASSWORD not set")
    from src.serving.setup_reader import setup

    user = setup()
    conn = psycopg.connect(host=os.getenv("POSTGRES_HOST", "localhost"),
                           port=int(os.getenv("POSTGRES_PORT", "5433")),
                           dbname=os.getenv("POSTGRES_DB", "kenya_jobs"), user=user, password=password)
    try:
        for view in ("dw.v_skill_demand", "dw.v_county_summary", "dw.v_coverage_overall", "dw.v_lifetime_summary"):
            conn.execute(f"SELECT * FROM {view} LIMIT 1")
            conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM dw.v_analytics_base LIMIT 1")
    finally:
        conn.close()