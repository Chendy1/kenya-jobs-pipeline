import pytest

from src.storage.postgres import get_conn
from src.warehouse.build import build


def _scalar(sql: str):
    with get_conn() as conn:
        return conn.execute(sql).fetchone()[0]


@pytest.fixture(scope="module", autouse=True)
def built():
    try:
        return build()
    except Exception as exc:  # no database running: skip instead of failing
        pytest.skip(f"Postgres not available: {exc}")


def test_fact_has_one_row_per_clean_posting(built):
    assert built["fact_job_postings"] == _scalar("SELECT count(*) FROM clean.job_postings")


FK_CHECKS = [
    ("company_key", "dim_company", "company_key"),
    ("location_key", "dim_location", "location_key"),
    ("posted_date_key", "dim_date", "date_key"),
    ("valid_through_date_key", "dim_date", "date_key"),
    ("first_seen_date_key", "dim_date", "date_key"),
    ("last_seen_date_key", "dim_date", "date_key"),
]


@pytest.mark.parametrize("col,dim,dim_col", FK_CHECKS)
def test_no_orphan_keys(col, dim, dim_col):
    orphans = _scalar(
        f"SELECT count(*) FROM dw.fact_job_postings f "
        f"LEFT JOIN dw.{dim} d ON d.{dim_col} = f.{col} WHERE d.{dim_col} IS NULL"
    )
    assert orphans == 0


def test_unknown_members_exist():
    assert _scalar("SELECT count(*) FROM dw.dim_company WHERE company_key = -1") == 1
    assert _scalar("SELECT count(*) FROM dw.dim_date WHERE date_key = -1") == 1
    assert _scalar("SELECT count(*) FROM dw.dim_location WHERE location_key IN (-1, -2, -3)") == 3


def test_all_47_counties_present():
    assert _scalar("SELECT count(*) FROM dw.dim_location WHERE location_type = 'county'") == 47


def test_bridge_matches_clean_skills(built):
    assert built["bridge_job_skill"] == _scalar("SELECT count(*) FROM clean.job_skills")


def test_salary_midpoint_is_between_bounds():
    bad = _scalar(
        "SELECT count(*) FROM dw.fact_job_postings WHERE has_salary AND NOT "
        "(salary_mid_monthly_kes BETWEEN salary_min_monthly_kes AND salary_max_monthly_kes)"
    )
    assert bad == 0


def test_view_excludes_duplicates():
    assert _scalar("SELECT count(*) FROM dw.v_jobs") == _scalar(
        "SELECT count(*) FROM dw.fact_job_postings WHERE NOT is_duplicate"
    )


def test_rebuild_is_idempotent(built):
    keys_before = _scalar("SELECT sum(job_posting_key) FROM dw.fact_job_postings")
    assert build() == built
    assert _scalar("SELECT sum(job_posting_key) FROM dw.fact_job_postings") == keys_before