"""Declarative data-quality checks.

Every check is one SQL query returning a single row: (violations, total).
The vocabulary mirrors dbt tests and Great Expectations:
    not_null, unique, accepted_values, relationships, expression_is_true,
    row_count_between, max_age_days.

severity "error": fails the run and blocks the warehouse build. "warn": reported, not blocking.
max_fraction: share of rows allowed to violate before the check fails (0 = zero tolerance).
Table and column names come from constants in this file, never from user input.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.extractors.policy import POLICY


@dataclass(frozen=True)
class Check:
    name: str
    layer: str
    severity: str  # "error" | "warn"
    sql: str
    description: str
    max_fraction: float = 0.0


def _lit(value) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _layer(table: str) -> str:
    return table.split(".")[0]


def _where(where: str | None) -> str:
    return f" WHERE {where}" if where else ""


def not_null(table, column, severity="error", max_fraction=0.0, where=None) -> Check:
    sql = f"SELECT count(*) FILTER (WHERE {column} IS NULL), count(*) FROM {table}{_where(where)}"
    return Check(f"{table}.{column}.not_null", _layer(table), severity, sql,
                 f"{column} should not be NULL", max_fraction)


def unique(table, columns, severity="error") -> Check:
    cols = ", ".join(columns)
    sql = (f"SELECT COALESCE(sum(n - 1), 0), (SELECT count(*) FROM {table}) FROM "
           f"(SELECT count(*) AS n FROM {table} GROUP BY {cols} HAVING count(*) > 1) d")
    return Check(f"{table}.{'+'.join(columns)}.unique", _layer(table), severity, sql,
                 f"({cols}) should be unique")


def accepted_values(table, column, values, severity="error") -> Check:
    listed = ", ".join(_lit(v) for v in values)
    sql = (f"SELECT count(*) FILTER (WHERE {column} IS NOT NULL AND {column} NOT IN ({listed})), "
           f"count(*) FROM {table}")
    return Check(f"{table}.{column}.accepted_values", _layer(table), severity, sql,
                 f"{column} should be one of {list(values)}")


def relationships(table, column, ref_table, ref_column, severity="error") -> Check:
    sql = (f"SELECT count(*) FILTER (WHERE t.{column} IS NOT NULL AND r.{ref_column} IS NULL), count(*) "
           f"FROM {table} t LEFT JOIN {ref_table} r ON r.{ref_column} = t.{column}")
    return Check(f"{table}.{column}.relationships", _layer(table), severity, sql,
                 f"{column} should exist in {ref_table}.{ref_column}")


def expression_is_true(table, expression, name, severity="error", where=None, max_fraction=0.0) -> Check:
    """NULL results pass (as in dbt_utils): only rows where the expression is FALSE violate."""
    sql = f"SELECT count(*) FILTER (WHERE ({expression}) IS FALSE), count(*) FROM {table}{_where(where)}"
    return Check(f"{table}.{name}", _layer(table), severity, sql, expression, max_fraction)


def row_count_between(table, minimum, maximum=None, severity="error") -> Check:
    cond = f"count(*) < {minimum}" + (f" OR count(*) > {maximum}" if maximum is not None else "")
    sql = f"SELECT CASE WHEN {cond} THEN 1 ELSE 0 END, 1 FROM {table}"
    return Check(f"{table}.row_count", _layer(table), severity, sql,
                 f"row count between {minimum} and {maximum if maximum is not None else 'infinity'}")


def max_age_days(table, column, days, severity="warn", where=None) -> Check:
    sql = (f"SELECT CASE WHEN max({column}) IS NULL "
           f"OR max({column}) < (now() AT TIME ZONE 'Africa/Nairobi')::date - {days} THEN 1 ELSE 0 END, 1 "
           f"FROM {table}{_where(where)}")
    return Check(f"{table}.{column}.max_age_{days}d", _layer(table), severity, sql,
                 f"newest {column} should be within {days} days")


def custom(name, layer, sql, description, severity="error", max_fraction=0.0) -> Check:
    return Check(name, layer, severity, sql, description, max_fraction)


def seen_recently(source, days=3, severity="error", allow_empty=False) -> Check:
    when_empty = 0 if allow_empty else 1
    sql = (f"SELECT CASE WHEN count(*) = 0 THEN {when_empty} "
           f"WHEN max(seen_on) < (now() AT TIME ZONE 'Africa/Nairobi')::date - {days} THEN 1 "
           f"ELSE 0 END, 1 FROM raw.sightings WHERE source = {_lit(source)}")
    return custom(f"ops.{source}.seen_within_{days}d", "ops", sql,
                  f"{source} should have been seen within {days} days", severity)


def volume_drop(source, ratio=0.5, severity="warn") -> Check:
    """Latest day's distinct postings vs the average of the previous 7 days (needs 3+ days of history)."""
    sql = f"""
        WITH daily AS (
            SELECT seen_on, count(*) AS n FROM raw.sightings
            WHERE source = {_lit(source)} GROUP BY seen_on
        ), latest AS (
            SELECT n FROM daily ORDER BY seen_on DESC LIMIT 1
        ), base AS (
            SELECT avg(n) AS a, count(*) AS d
            FROM (SELECT n FROM daily ORDER BY seen_on DESC OFFSET 1 LIMIT 7) t
        )
        SELECT CASE WHEN base.d >= 3 AND latest.n < {ratio} * base.a THEN 1 ELSE 0 END, 1
        FROM latest CROSS JOIN base"""
    return custom(f"ops.{source}.volume_drop", "ops", sql,
                  f"{source} postings seen today should not fall below {ratio:.0%} of the recent average",
                  severity)


def all_checks() -> list[Check]:
    cj, fact = "clean.job_postings", "dw.fact_job_postings"
    checks: list[Check] = [
        # ---------------- raw ----------------
        row_count_between("raw.job_postings", 1),
        not_null("raw.job_postings", "job_key"),
        not_null("raw.job_postings", "content_hash"),
        accepted_values("raw.job_postings", "source", sorted(POLICY)),
        expression_is_true("raw.job_postings", "jsonb_typeof(payload) = 'object'", "payload_is_object"),
        # ---------------- clean ----------------
        row_count_between(cj, 1),
        unique(cj, ["source", "job_key"]),
        not_null(cj, "title_clean", max_fraction=0.02),
        not_null(cj, "date_posted", severity="warn", max_fraction=0.02),
        not_null(cj, "company", severity="warn", max_fraction=0.10),
        not_null(cj, "county_code", severity="warn", max_fraction=0.20),
        not_null(cj, "description_text", severity="warn", max_fraction=0.25),
        accepted_values(cj, "seniority",
                        ["director", "manager", "senior", "mid", "junior", "intern", "unspecified"]),
        accepted_values(cj, "salary_source", ["structured", "text"]),
        expression_is_true(cj, "salary_min_monthly_kes <= salary_max_monthly_kes", "salary_min_lte_max"),
        expression_is_true(cj, "salary_min_monthly_kes >= 5000", "salary_min_above_floor"),
        expression_is_true(cj, "date_posted <= (now() AT TIME ZONE 'Africa/Nairobi')::date + 1",
                           "date_not_in_future"),
        expression_is_true(cj, "date_posted >= DATE '2015-01-01'", "date_not_ancient", severity="warn"),
        expression_is_true(cj, "valid_through >= date_posted", "valid_through_after_posted", severity="warn"),
        expression_is_true(cj, "(NOT is_duplicate) OR canonical_job_key IS NOT NULL",
                           "duplicates_have_a_canonical"),
        max_age_days(cj, "date_posted", 14),
        # ---------------- warehouse ----------------
        row_count_between(fact, 1),
        row_count_between("dw.dim_location", 50, 50),
        unique(fact, ["source", "job_key"]),
        relationships(fact, "company_key", "dw.dim_company", "company_key"),
        relationships(fact, "location_key", "dw.dim_location", "location_key"),
        relationships(fact, "posted_date_key", "dw.dim_date", "date_key"),
        relationships("dw.bridge_job_skill", "skill_key", "dw.dim_skill", "skill_key"),
        expression_is_true(fact, "salary_mid_monthly_kes BETWEEN salary_min_monthly_kes "
                                 "AND salary_max_monthly_kes", "salary_mid_between_bounds", where="has_salary"),
        expression_is_true(fact, "days_advertised >= 0", "days_advertised_non_negative"),
        expression_is_true(fact, "last_seen_date_key >= first_seen_date_key", "last_seen_after_first_seen"),
        expression_is_true(fact, "location_key <> -1", "location_known", severity="warn", max_fraction=0.20),
        custom("dw.fact_matches_clean", "dw",
               "SELECT abs((SELECT count(*) FROM dw.fact_job_postings) - "
               "(SELECT count(*) FROM clean.job_postings)), (SELECT count(*) FROM clean.job_postings)",
               "the fact table should have one row per clean posting"),
        custom("dw.bridge_matches_clean_skills", "dw",
               "SELECT abs((SELECT count(*) FROM dw.bridge_job_skill) - "
               "(SELECT count(*) FROM clean.job_skills)), (SELECT count(*) FROM clean.job_skills)",
               "the bridge table should have one row per clean skill row"),
        custom("dw.skill_count_matches_bridge", "dw",
               "SELECT count(*) FILTER (WHERE f.skill_count <> COALESCE(b.n, 0)), count(*) "
               "FROM dw.fact_job_postings f LEFT JOIN "
               "(SELECT job_posting_key, count(*) AS n FROM dw.bridge_job_skill GROUP BY 1) b "
               "USING (job_posting_key)",
               "fact.skill_count should equal the number of bridge rows"),
    ]
    # ---------------- ops: freshness and volume ----------------
    checks.append(seen_recently("myjobmag", days=3, severity="error"))
    for source in ("jsearch", "reliefweb", "jooble"):  # optional sources: fine until they have data
        checks.append(seen_recently(source, days=7, severity="warn", allow_empty=True))
    for source in ("myjobmag", "jsearch"):
        checks.append(volume_drop(source))
    return checks