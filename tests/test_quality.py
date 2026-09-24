import json
import logging

import pytest

from src.ops.logs import JsonFormatter
from src.ops.notify import notify
from src.quality.checks import (Check, accepted_values, all_checks, expression_is_true, not_null,
                                relationships, row_count_between, unique)
from src.quality.runner import Result, _run_one, run_checks, summarize
from src.storage.postgres import get_conn, init_schema


def test_check_names_are_unique_and_valid():
    checks = all_checks()
    names = [c.name for c in checks]
    assert len(names) == len(set(names))
    assert all(c.severity in ("error", "warn") for c in checks)
    assert {c.layer for c in checks} == {"raw", "clean", "dw", "ops"}


def test_summarize_separates_errors_from_warnings():
    results = [Result("a", "clean", "error", 1, 10, False, ""),
               Result("b", "clean", "warn", 1, 10, False, ""),
               Result("c", "clean", "error", 0, 10, True, "")]
    s = summarize(results)
    assert s["errors"] == ["a"] and s["warnings"] == ["b"] and s["passed"] == 1


def test_notify_never_raises_without_channels(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "ALERT_EMAIL_TO"):
        monkeypatch.delenv(var, raising=False)
    assert notify("test", "body") == {"telegram": "not configured", "email": "not configured"}


def test_json_formatter_keeps_extra_fields():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.source = "myjobmag"
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello world" and out["source"] == "myjobmag" and out["level"] == "INFO"


@pytest.fixture
def db():
    try:
        init_schema()
        with get_conn() as conn:
            conn.execute(
                "DROP SCHEMA IF EXISTS dq_test CASCADE; CREATE SCHEMA dq_test; "
                "CREATE TABLE dq_test.t (a int, b text); "
                "INSERT INTO dq_test.t VALUES (1,'x'), (2,NULL), (2,'y'), (3,NULL); "
                "CREATE TABLE dq_test.r (id int); INSERT INTO dq_test.r VALUES (1), (2);")
    except Exception as exc:  # no database running: skip instead of failing
        pytest.skip(f"Postgres not available: {exc}")
    yield
    with get_conn() as conn:
        conn.execute("DROP SCHEMA IF EXISTS dq_test CASCADE")


def _run(check: Check) -> Result:
    with get_conn() as conn:
        return _run_one(conn, check)


def test_check_types_catch_bad_data(db):
    assert not _run(not_null("dq_test.t", "b", max_fraction=0.25)).passed  # 2 of 4 are NULL
    assert _run(not_null("dq_test.t", "b", max_fraction=0.5)).passed       # exactly at the limit
    assert not _run(unique("dq_test.t", ["a"])).passed                     # a=2 appears twice
    assert not _run(accepted_values("dq_test.t", "b", ["x"])).passed       # 'y' is not allowed
    assert not _run(relationships("dq_test.t", "a", "dq_test.r", "id")).passed  # a=3 has no parent
    assert not _run(expression_is_true("dq_test.t", "a < 3", "a_below_3")).passed
    assert not _run(row_count_between("dq_test.t", 5)).passed
    assert _run(row_count_between("dq_test.t", 1, 10)).passed


def test_a_check_that_cannot_run_counts_as_failed(db):
    bad = Check("dq_test.bad", "dq_test", "error", "SELECT nope FROM dq_test.t", "broken on purpose")
    result = _run(bad)
    assert not result.passed and result.detail.startswith("check could not run")


def test_every_real_check_runs_against_the_live_schema(db):
    from src.warehouse.build import build

    build()  # make sure the dw tables exist
    broken = [r.name for r in run_checks() if r.detail.startswith("check could not run")]
    assert broken == []