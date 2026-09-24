"""Run any registered source end to end: extract -> raw layer (+ HTML snapshots) -> Postgres.

    python -m src.pipeline.run_source --list
    python -m src.pipeline.run_source --source myjobmag --max 10 --pages 1
    python -m src.pipeline.run_source --source reliefweb --max 100
    python -m src.pipeline.run_source --source jsearch --max 30
    python -m src.pipeline.run_source --source jsearch --quota
"""
from __future__ import annotations

import argparse
import gzip
import logging

from src.extractors.base import html_key
from src.extractors.policy import POLICY, SourceNotAllowed
from src.extractors.registry import available, build
from src.pipeline.ingest import ingest
from src.storage.raw_store import get_store, utcnow

log = logging.getLogger(__name__)


def run(source: str, max_items: int = 30, backend: str | None = None, **opts) -> tuple[int, int]:
    extractor = build(source, **opts)  # the policy check happens inside build()
    store = get_store(backend)
    day = utcnow().strftime("%Y-%m-%d")

    def already_done(snapshot_id: str) -> bool:
        return store.exists(html_key(source, snapshot_id, day))

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
    log.info("%s: fetched=%d new_rows=%d", source, len(records), inserted)
    return len(records), inserted


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show every source and its policy status")
    ap.add_argument("--source")
    ap.add_argument("--max", type=int, default=30)
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
        run(args.source, args.max, args.backend, **opts)
    except SourceNotAllowed as exc:
        raise SystemExit(f"Refused: {exc}")


if __name__ == "__main__":
    main()