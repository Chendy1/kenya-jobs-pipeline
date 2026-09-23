"""Re-extract saved HTML snapshots with the current extractor; ingest as NEW versions.

Raw is immutable: this appends new versions and never edits old ones. No web requests.
    python -m src.pipeline.reparse --source brightermonday --dry-run
    python -m src.pipeline.reparse --source brightermonday
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from src.extractors.jsonld import build_record
from src.pipeline.ingest import ingest
from src.storage.postgres import get_conn

log = logging.getLogger(__name__)


def known_urls(source: str) -> dict[str, str]:
    """sha1(url)[:16] -> url, from job_keys already in Postgres (job_key IS the URL)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT job_key FROM raw.job_postings WHERE source = %s", (source,))
        return {hashlib.sha1(k.encode()).hexdigest()[:16]: k for (k,) in cur.fetchall()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    base = Path(os.getenv("RAW_LOCAL_DIR", "data")) / "raw_html" / f"source={args.source}"
    urls = known_urls(args.source)
    latest: dict[str, dict] = {}  # one record per page; a later day's snapshot wins
    unknown = no_posting = 0
    for path in sorted(base.rglob("*.html.gz")):
        stem = path.name.removesuffix(".html.gz")
        url = urls.get(stem)
        if not url:
            unknown += 1
            log.warning("No known URL for snapshot %s (skipped)", path.name)
            continue
        html = gzip.decompress(path.read_bytes()).decode("utf-8")
        # fetched_at is ignored by the content hash, so a future real scrape of an
        # unchanged page will NOT create yet another version.
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        record = build_record(args.source, url, html, fetched_at)
        if record is None:
            no_posting += 1
            continue
        latest[stem] = record

    log.info("%d records rebuilt (%d unknown URL, %d without JobPosting)",
             len(latest), unknown, no_posting)
    if args.dry_run or not latest:
        log.info("Nothing written")
        return
    _, inserted = ingest(args.source, list(latest.values()))
    log.info("%d new versions inserted", inserted)


if __name__ == "__main__":
    main()