"""Run any registered source end to end, incrementally:
extract -> raw layer (+ HTML snapshots) -> Postgres -> sightings log.

    python -m src.pipeline.run_source --list
    python -m src.pipeline.run_source --source myjobmag --max 10 --pages 1
    python -m src.pipeline.run_source --source reliefweb --max 100
    python -m src.pipeline.run_source --source jsearch --max 30
    python -m src.pipeline.run_source --source jsearch --quota
    python -m src.pipeline.run_source --source jsearch --force     # ignore the quota guard
"""
from __future__ import annotations

import argparse
import gzip
import logging

from src.extractors.base import html_key
from src.extractors.policy import POLICY, SourceNotAllowed
from src.extractors.registry import available, build
from src.pipeline.ingest import ingest
from src.storage.postgres import advisory_lock, fresh_keys, get_conn, record_sightings
from src.storage.raw_store import get_store, job_key, utcnow

log = logging.getLogger(__name__)

# Quota protection: these API sources run at most once per this many hours unless forced.

MIN_HOURS_BETWEEN_RUNS = {"jsearch": 20, "jooble": 20, "reliefweb": 20, "remotive": 12}


def hours_since_last_run(source: str) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT extract(epoch FROM now() - max(loaded_at)) / 3600 "
            "FROM raw.ingest_runs WHERE source = %s", (source,)).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _run_locked(source: str, max_items: int = 30, backend: str | None = None,
        refresh_days: int = 14, force: bool = False, **opts) -> dict:
    extractor = build(source, **opts)  # policy check + credentials check happen here

    gate = MIN_HOURS_BETWEEN_RUNS.get(source)
    if gate and not force:
        hours = hours_since_last_run(source)
        if hours is not None and hours < gate:
            log.warning("%s throttled: last run %.1f h ago (minimum %d h). Use --force to override.",
                        source, hours, gate)
            return {"source": source, "status": "throttled", "seen": 0, "skipped_known": 0,
                    "fetched": 0, "new_rows": 0}

    store = get_store(backend)
    day = utcnow().strftime("%Y-%m-%d")
    fresh = fresh_keys(source, refresh_days)
    known_skipped: set[str] = set()

    def already_done(snapshot_id: str) -> bool:
        done = snapshot_id in fresh or store.exists(html_key(source, snapshot_id, day))
        if done:
            known_skipped.add(snapshot_id)  # a set: the same URL can show up on several listings
        return done

    records, snapshots = [], {}
    for item in extractor.fetch(max_items, already_done):
        records.append(item.record)
        if item.snapshot is not None and item.snapshot_id:
            snapshots[html_key(source, item.snapshot_id, day)] = item.snapshot

    inserted = 0
    if records:
        _, inserted = ingest(source, records, backend)
        # snapshots last: they double as the "already fetched today" marker
        for key, html in snapshots.items():
            store.write(key, gzip.compress(html.encode("utf-8")))

    fetched_keys = {job_key(r) for r in records}
    seen_keys = set(getattr(extractor, "seen", set())) | fetched_keys
    record_sightings(source, seen_keys, fetched_keys)

    result = {"source": source, "status": "ok" if seen_keys else "empty",
              "seen": len(seen_keys), "skipped_known": len(known_skipped),
              "fetched": len(records), "new_rows": inserted}
    if not seen_keys:
        log.warning("%s returned nothing: check credentials, filters or coverage", source)
    log.info("%(source)s: status=%(status)s seen=%(seen)d skipped_known=%(skipped_known)d "
             "fetched=%(fetched)d new_rows=%(new_rows)d", result)
    return result


def run(source: str, max_items: int = 30, backend: str | None = None,
        refresh_days: int = 14, force: bool = False, **opts) -> dict:
    """One run per source at a time, across every process. Two concurrent runs would
    double the request rate on the site and let the quota check race with itself."""
    with advisory_lock(f"pipeline:{source}") as acquired:
        if not acquired:
            log.warning("%s is already running elsewhere: skipping this run", source)
            return {"source": source, "status": "busy", "seen": 0, "skipped_known": 0,
                    "fetched": 0, "new_rows": 0}
        return _run_locked(source, max_items, backend, refresh_days, force, **opts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show every source and its policy status")
    ap.add_argument("--source")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--refresh-days", type=int, default=14,
                    help="re-download a posting only if last fetched more than this many days ago")
    ap.add_argument("--force", action="store_true", help="ignore the once-per-20-hours API quota guard")
    ap.add_argument("--pages", type=int, default=2, help="myjobmag: listing pages to read")
    ap.add_argument("--listing", help="myjobmag: a listing URL instead of the homepage feed")
    ap.add_argument("--backend", choices=["local", "s3"])
    ap.add_argument("--quota", action="store_true", help="jsearch: show remaining monthly quota")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.list:
        ready = set(available())
        for name, p in sorted(POLICY.items()):
            print(f"{name:<16}{p.status:<18}{'extractor ready' if name in ready else ''}")
        return
    if not args.source:
        ap.error("use --list or --source")
    if args.quota and args.source != "jsearch":
        ap.error("--quota only applies to --source jsearch")

    opts = {"listing_url": args.listing, "pages": args.pages} if args.source == "myjobmag" else {}
    try:
        if args.quota:
            print(build("jsearch").usage())
            return
        run(args.source, args.max, args.backend, args.refresh_days, args.force, **opts)
    except SourceNotAllowed as exc:
        raise SystemExit(f"Refused: {exc}")


if __name__ == "__main__":
    main()