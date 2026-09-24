"""Run checks, persist the results, summarise them."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from src.quality.checks import Check, all_checks
from src.storage.postgres import get_conn

log = logging.getLogger(__name__)


@dataclass
class Result:
    name: str
    layer: str
    severity: str
    violations: int
    total: int
    passed: bool
    detail: str


def _run_one(conn, check: Check) -> Result:
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute(check.sql)
            row = cur.fetchone()
        conn.commit()
    except Exception as exc:  # a check that cannot run is a FAILED check, never a silent pass
        conn.rollback()
        message = (str(exc).splitlines() or [""])[0][:160]
        return Result(check.name, check.layer, check.severity, 0, 0, False,
                      f"check could not run: {type(exc).__name__}: {message}")
    if row is None:
        return Result(check.name, check.layer, check.severity, 0, 0, True, "no data")
    violations, total = int(row[0] or 0), int(row[1] or 0)
    passed = violations <= check.max_fraction * total
    detail = f"{violations}/{total} violating"
    if check.max_fraction:
        detail += f" (allowed {check.max_fraction:.0%})"
    return Result(check.name, check.layer, check.severity, violations, total, passed, detail)


def run_checks(layer: str | None = None) -> list[Result]:
    selected = [c for c in all_checks() if layer is None or c.layer == layer]
    with get_conn() as conn:
        return [_run_one(conn, c) for c in selected]


def save_results(results: list[Result]) -> None:
    if not results:
        return
    rows = [(r.name, r.layer, r.severity, r.violations, r.total, r.passed, r.detail) for r in results]
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ops.dq_results (check_name, layer, severity, violations, total, passed, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)


def summarize(results: list[Result]) -> dict:
    failed = [r for r in results if not r.passed]
    return {"total": len(results), "passed": len(results) - len(failed),
            "errors": [r.name for r in failed if r.severity == "error"],
            "warnings": [r.name for r in failed if r.severity == "warn"]}