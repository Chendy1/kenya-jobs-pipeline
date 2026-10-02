import pytest

from src.storage.postgres import fresh_keys, get_conn, init_schema, record_sightings


def test_configured_sources_skips_unconfigured(monkeypatch):
    from src.flows.daily import configured_sources

    monkeypatch.delenv("PIPELINE_SOURCES", raising=False)
    for var in ("RELIEFWEB_APPNAME", "JSEARCH_API_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JSEARCH_API_KEY", "x")
    
    
    ready, skipped = configured_sources(None)
    assert ready == ["myjobmag", "jsearch", "remotive", "oyk"]
    assert set(skipped) == {"reliefweb"}

@pytest.fixture
def db():
    try:
        init_schema()
    except Exception as exc:  # no database running: skip instead of failing
        pytest.skip(f"Postgres not available: {exc}")
    yield
    with get_conn() as conn:
        conn.execute("DELETE FROM raw.sightings WHERE source = 'test_sightings'")


def test_sightings_are_idempotent_within_a_day(db):
    record_sightings("test_sightings", {"a", "b"}, {"a"})
    record_sightings("test_sightings", {"a", "b"}, {"b"})  # same day: no duplicates, flags combine
    with get_conn() as conn:
        rows = conn.execute("SELECT job_key, fetched FROM raw.sightings "
                            "WHERE source = 'test_sightings' ORDER BY job_key").fetchall()
    assert rows == [("a", True), ("b", True)]
    assert fresh_keys("test_sightings", 14) == {"a", "b"}

def test_advisory_lock_blocks_a_second_holder(db):
    from src.storage.postgres import advisory_lock

    with advisory_lock("test:lock") as first:
        assert first is True
        with advisory_lock("test:lock") as second:
            assert second is False
    with advisory_lock("test:lock") as again:
        assert again is True