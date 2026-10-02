"""The daily pipeline:
sources -> transform -> quality gate -> warehouse -> quality checks -> record -> alert.

    python -m src.flows.daily                    # run once, now
    python -m src.flows.daily --skip-extract     # re-run only transform, checks and warehouse
Scheduled runs: see src/flows/serve.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from prefect import flow, get_run_logger, task

from src.extractors.policy import SourceNotAllowed
from src.ops.logs import configure_logging
from src.ops.notify import notify
from src.ops.runlog import record_run
from src.pipeline.run_source import run as run_source
from src.quality.runner import run_checks, save_results, summarize
from src.storage.postgres import get_conn
from src.storage.raw_store import utcnow
from src.transform.run import fetch_latest, load, transform_row
from src.warehouse.build import build

load_dotenv()


DEFAULT_SOURCES = ["myjobmag", "reliefweb", "jsearch", "remotive", "oyk"]
REQUIRED_ENV = {"reliefweb": "RELIEFWEB_APPNAME", "jsearch": "JSEARCH_API_KEY", "jooble": "JOOBLE_API_KEY"}


class PipelineFailed(RuntimeError):
    pass


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


@task(name="extract-and-load", retries=2, retry_delay_seconds=[60, 300])
def extract_source(source: str, max_items: int, refresh_days: int) -> dict:
    logger = get_run_logger()
    opts = {"pages": 2} if source in ("myjobmag", "oyk") else {}
    try:
        limit = min(max_items, 8) if source == "oyk" else max_items  # 120s crawl-delay per request
        return run_source(source, limit, refresh_days=refresh_days, **opts)
    except SourceNotAllowed as exc:  # a policy decision, not an outage: never retry
        logger.warning("%s refused: %s", source, exc)
        return {"source": source, "status": "refused", "reason": str(exc)}
    # network errors propagate, so Prefect retries them


@task(name="transform", retries=1, retry_delay_seconds=30)
def transform() -> int:
    with get_conn() as conn:
        results = [transform_row(row) for row in fetch_latest(conn, None)]
        load(conn, results)
    return len(results)


@task(name="build-warehouse", retries=1, retry_delay_seconds=30)
def build_warehouse() -> dict:
    return build()


@task(name="quality-checks")
def quality_gate(layer: str) -> dict:
    results = run_checks(layer)
    save_results(results)
    for r in results:
        if not r.passed:
            print(f"[{r.severity.upper()}] {r.name}: {r.detail}")
    return summarize(results)



def _execute(sources, max_items: int, refresh_days: int, skip_extract: bool) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    ready, skipped = ([], {}) if skip_extract else configured_sources(sources)
    for source, why in skipped.items():
        notes.append(f"skipped {source}: {why}")

    futures = {s: extract_source.submit(s, max_items, refresh_days) for s in ready}
    outcomes: dict[str, dict] = {}
    for source, future in futures.items():
        try:
            outcomes[source] = future.result()
        except Exception as exc:  # retries exhausted: record it, keep going with the other sources
            outcomes[source] = {"source": source, "status": "failed",
                                "reason": f"{type(exc).__name__}: {exc}"}
        status = outcomes[source]["status"]
        print(f"{source}: {outcomes[source]}")
        if status == "failed":
            errors.append(f"source {source} failed: {outcomes[source]['reason']}")
        elif status == "empty":
            warnings.append(f"source {source} returned nothing")
        elif status in ("refused", "throttled", "busy"):
            notes.append(f"{source}: {status}")

    # Gate 1 (raw): if the raw layer is bad, touch nothing downstream.
    dq: dict[str, dict] = {"raw": quality_gate("raw")}
    clean_rows = None
    warehouse = None
    if dq["raw"]["errors"]:
        errors.append("transform and warehouse build skipped because the raw-layer quality gate "
                      "failed; clean data and warehouse are untouched")
    else:
        clean_rows = transform()
        # Gate 2 (clean): protects the warehouse, which is what gets served.
        dq["clean"] = quality_gate("clean")
        if dq["clean"]["errors"]:
            errors.append("warehouse build skipped because the clean-layer quality gate failed; "
                          "the previous warehouse is untouched")
        else:
            warehouse = build_warehouse()
            dq["dw"] = quality_gate("dw")
    dq["ops"] = quality_gate("ops")

    for layer_summary in dq.values():
        errors += [f"data quality [{name}]" for name in layer_summary["errors"]]
        warnings += [f"data quality [{name}]" for name in layer_summary["warnings"]]

    return {"outcomes": outcomes, "notes": notes, "clean_rows": clean_rows,
            "warehouse": warehouse, "dq": dq, "errors": errors, "warnings": warnings}

def _finish(started, summary: dict, crashed: bool = False) -> None:
    errors, warnings = summary.get("errors", []), summary.get("warnings", [])
    status = "crashed" if crashed else "failed" if errors else "warnings" if warnings else "ok"
    record_run(started, utcnow(), status, summary)
    lines = [f"- {e}" for e in errors] + [f"- (warning) {w}" for w in warnings]
    if errors:
        notify("Kenya jobs pipeline FAILED", "\n".join(lines), level="error",
               dedupe_key="|".join(sorted(errors)), dedupe_hours=12)
    elif warnings:
        notify("Kenya jobs pipeline: warnings", "\n".join(lines), level="warn",
               dedupe_key="|".join(sorted(warnings)), dedupe_hours=72)


@flow(name="kenya-jobs-daily", log_prints=True)
def daily_pipeline(sources: list[str] | None = None, max_items: int = 30,
                   refresh_days: int = 14, skip_extract: bool = False) -> dict:
    configure_logging(console=False)  # Prefect already prints to the console
    started = utcnow()
    try:
        summary = _execute(sources, max_items, refresh_days, skip_extract)
    except Exception as exc:
        _finish(started, {"errors": [f"pipeline crashed: {type(exc).__name__}: {exc}"], "warnings": []},
                crashed=True)
        raise
    _finish(started, summary)
    if summary["errors"]:
        raise PipelineFailed("; ".join(summary["errors"]))
    return summary

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-extract", action="store_true", help="only transform, check and rebuild")
    try:
        daily_pipeline(skip_extract=ap.parse_args().skip_extract)
    except PipelineFailed as exc:
        raise SystemExit(f"Pipeline failed: {exc}")

