"""The daily pipeline: every configured source -> transform -> warehouse.

    python -m src.flows.daily        # run once, now
Scheduled runs: see src/flows/serve.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task

from src.extractors.policy import SourceNotAllowed
from src.pipeline.run_source import run as run_source
from src.storage.postgres import get_conn
from src.transform.run import fetch_latest, load, transform_row
from src.warehouse.build import build

load_dotenv()

DEFAULT_SOURCES = ["myjobmag", "reliefweb", "jsearch", "jooble"]
REQUIRED_ENV = {"reliefweb": "RELIEFWEB_APPNAME", "jsearch": "JSEARCH_API_KEY", "jooble": "JOOBLE_API_KEY"}


def configured_sources(requested: list[str] | None = None) -> tuple[list[str], dict[str, str]]:
    """Split the wanted sources into (ready, skipped-with-reason). An API source without
    credentials is skipped, not failed: not being set up yet is not an outage."""
    wanted = requested or [s.strip() for s in
                           os.getenv("PIPELINE_SOURCES", ",".join(DEFAULT_SOURCES)).split(",") if s.strip()]
    ready: list[str] = []
    skipped: dict[str, str] = {}
    for source in wanted:
        var = REQUIRED_ENV.get(source)
        if var and not os.getenv(var):
            skipped[source] = f"{var} is not set"
        else:
            ready.append(source)
    return ready, skipped


@task(name="extract-and-load", retries=2, retry_delay_seconds=[60, 300], timeout_seconds=1800)
def extract_source(source: str, max_items: int, refresh_days: int) -> dict:
    logger = get_run_logger()
    opts = {"pages": 2} if source == "myjobmag" else {}
    try:
        result = run_source(source, max_items, refresh_days=refresh_days, **opts)
    except SourceNotAllowed as exc:  # a policy decision, not an outage: never retry
        logger.warning("%s refused: %s", source, exc)
        return {"source": source, "status": "refused", "reason": str(exc)}
    return {**result, "status": "ok"}  # network errors propagate, so Prefect retries them


@task(name="transform", retries=1, retry_delay_seconds=30)
def transform() -> int:
    with get_conn() as conn:
        results = [transform_row(row) for row in fetch_latest(conn, None)]
        load(conn, results)
    return len(results)


@task(name="build-warehouse", retries=1, retry_delay_seconds=30)
def build_warehouse() -> dict:
    return build()


@flow(name="kenya-jobs-daily", log_prints=True)
def daily_pipeline(sources: list[str] | None = None, max_items: int = 30, refresh_days: int = 14) -> dict:
    ready, skipped = configured_sources(sources)
    for source, why in skipped.items():
        print(f"skipping {source}: {why}")

    futures = {s: extract_source.submit(s, max_items, refresh_days) for s in ready}
    outcomes: dict[str, dict] = {}
    for source, future in futures.items():
        try:
            outcomes[source] = future.result()
        except Exception as exc:  # retries exhausted: record it, keep going with the other sources
            outcomes[source] = {"source": source, "status": "failed",
                                "reason": f"{type(exc).__name__}: {exc}"}
        print(f"{source}: {outcomes[source]}")

    clean_rows = transform()  # runs on whatever arrived: it is idempotent
    warehouse = build_warehouse()

    failed = [s for s, o in outcomes.items() if o["status"] == "failed"]
    if failed:  # finish as FAILED so alerts (Phase 8) can fire, after the good data is loaded
        raise RuntimeError(f"extraction failed for: {', '.join(failed)}")
    return {"outcomes": outcomes, "skipped": skipped, "clean_rows": clean_rows, "warehouse": warehouse}


if __name__ == "__main__":
    daily_pipeline()