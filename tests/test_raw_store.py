from datetime import datetime, timezone

from src.storage.raw_store import LocalRawStore, content_hash, read_batch, wrap, write_batch


def test_round_trip(tmp_path):
    store = LocalRawStore(tmp_path)
    recs = [{"url": "https://example.com/job/1", "title": "Data Engineer"}]
    key, _, envs = write_batch(
        store, "brightermonday", recs,
        scraped_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    assert key.startswith("raw/source=brightermonday/dt=2026-09-23/")
    assert read_batch(store, key) == envs


def test_hash_ignores_fetched_at():
    a = content_hash({"url": "u", "fetched_at": "2026-09-23T10:00", "job_posting": {"title": "x"}})
    b = content_hash({"url": "u", "fetched_at": "2026-09-24T10:00", "job_posting": {"title": "x"}})
    assert a == b


def test_hash_ignores_key_order():
    now = datetime.now(timezone.utc)
    a = wrap({"url": "u", "x": 1, "y": 2}, "s", "r", now)
    b = wrap({"y": 2, "x": 1, "url": "u"}, "s", "r", now)
    assert a["content_hash"] == b["content_hash"]