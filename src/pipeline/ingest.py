"""Phase 3 entry point: write the raw layer, then load Postgres.

From the repo root with the venv active:
    python -m src.pipeline.ingest --init-db
    python -m src.pipeline.ingest --source brightermonday --input data/samples/sample.json
    python -m src.pipeline.ingest --replay raw/source=brightermonday/dt=2026-09-23
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from src.storage.postgres import init_schema, load_envelopes
from src.storage.raw_store import get_store, read_batch, write_batch

log = logging.getLogger(__name__)

def load_records_from_file(path: str) -> list[dict]:
    p = Path(path)
    if p.is_dir():  # a folder of one-posting-per-file JSON, like Phase 2 wrote
        records: list[dict] = []
        for f in sorted(p.glob("*.json")):
            records += load_records_from_file(str(f))
        return records
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if isinstance(data, dict):
        for k in ("jobs", "records", "items", "data", "results"):
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return data



def ingest(source: str, records: list[dict], backend: str | None = None,
           load_pg: bool = True) -> tuple[str, int]:
    """Call this from your extractor: ingest("brightermonday", records)."""
    store = get_store(backend)
    key, uri, envelopes = write_batch(store, source, records)
    log.info("Raw written: %s (%d records)", uri, len(envelopes))
    inserted = load_envelopes(envelopes, raw_key=key) if load_pg else 0
    return key, inserted


def replay(prefix: str, backend: str | None = None) -> int:
    """Rebuild Postgres from raw files. Proves the raw layer is the source of truth."""
    store = get_store(backend)
    keys = store.list_keys(prefix)
    log.info("Replaying %d raw file(s) under %s", len(keys), prefix)
    return sum(load_envelopes(read_batch(store, k), raw_key=k) for k in keys)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--init-db", action="store_true", help="create schema/tables")
    p.add_argument("--source", help="e.g. brightermonday")
    p.add_argument("--input", help="path to .json or .jsonl from your extractor")
    p.add_argument("--replay", help="raw key prefix to reload into Postgres")
    p.add_argument("--backend", choices=["local", "s3"], help="override RAW_BACKEND")
    p.add_argument("--no-pg", action="store_true", help="write raw files only")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.init_db:
        init_schema()
        log.info("Schema ready")
    elif args.replay:
        replay(args.replay, args.backend)
    elif args.source and args.input:
        ingest(args.source, load_records_from_file(args.input), args.backend,
               load_pg=not args.no_pg)
    else:
        p.error("Use --init-db, --replay, or --source with --input")


if __name__ == "__main__":
    main()