"""Phase 4 entry point: raw.job_postings -> clean.job_postings + clean.job_skills.

From the repo root with the venv active:
    python -m src.transform.run --dry-run      # transform + data-quality profile, writes nothing
    python -m src.transform.run                # rebuild clean tables from raw
    python -m src.transform.run --source brightermonday
"""
from __future__ import annotations

import argparse
import hashlib
import logging
from collections import Counter

from psycopg.rows import dict_row

from src.storage.postgres import get_conn
from src.transform.adapters import get_adapter
from src.transform.cleaners import (
    clean_company, clean_title, company_norm, html_to_text, norm_text, parse_date,
    parse_salary_structured, parse_salary_text, redact_contacts, seniority,
)
from src.transform.counties import COUNTIES, map_location
from src.transform.skills import extract_skills

log = logging.getLogger(__name__)

COLUMNS = [
    "source", "job_key", "raw_id", "url", "title_raw", "title_clean", "title_norm", "seniority",
    "company", "company_norm", "location_raw", "county", "county_code", "is_remote",
    "employment_type", "industry", "date_posted", "valid_through",
    "salary_currency", "salary_min", "salary_max", "salary_period",
    "salary_min_monthly_kes", "salary_max_monthly_kes", "salary_source",
    "description_text", "dedup_key", "first_seen_at", "last_seen_at",
]

UPSERT_SQL = (
    f"INSERT INTO clean.job_postings ({', '.join(COLUMNS)}) "
    f"VALUES ({', '.join(f'%({c})s' for c in COLUMNS)}) "
    "ON CONFLICT (source, job_key) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("source", "job_key"))
    + ", is_duplicate = FALSE, canonical_source = NULL, canonical_job_key = NULL,"
    " transformed_at = now()"
)

COUNTY_SQL = (
    "INSERT INTO ref.counties (county_code, county_name) VALUES (%s, %s) "
    "ON CONFLICT (county_code) DO UPDATE SET county_name = EXCLUDED.county_name"
)

SKILL_SQL = (
    "INSERT INTO clean.job_skills (source, job_key, skill, category) VALUES (%s, %s, %s, %s) "
    "ON CONFLICT DO NOTHING"
)

# Earliest-posted row in each dedup group is canonical; the others are flagged duplicates.
DEDUP_SQL = """
WITH ranked AS (
    SELECT source, job_key,
           first_value(source)  OVER w AS canon_source,
           first_value(job_key) OVER w AS canon_key,
           row_number()         OVER w AS rn
    FROM clean.job_postings
    WHERE dedup_key IS NOT NULL
    WINDOW w AS (PARTITION BY dedup_key
                 ORDER BY date_posted NULLS LAST, first_seen_at, source, job_key)
)
UPDATE clean.job_postings c
SET is_duplicate      = (r.rn > 1),
    canonical_source  = CASE WHEN r.rn > 1 THEN r.canon_source END,
    canonical_job_key = CASE WHEN r.rn > 1 THEN r.canon_key END
FROM ranked r
WHERE c.source = r.source AND c.job_key = r.job_key
"""



def fetch_latest(conn, sources: list[str] | None) -> list[dict]:
    """Latest version of each posting. first/last seen come from the sightings log,
    falling back to scrape times for postings that have no sightings yet."""
    where = ""
    params = None
    if sources:
        where = "WHERE source IN (" + ", ".join(["%s"] * len(sources)) + ")"
        params = tuple(sources)
    sql = f"""
        SELECT DISTINCT ON (r.source, r.job_key)
               r.id, r.source, r.job_key, r.payload,
               COALESCE(s.first_seen, r.first_scraped) AS first_seen,
               COALESCE(s.last_seen,  r.last_scraped)  AS last_seen
        FROM (
            SELECT id, source, job_key, payload, scraped_at,
                   min(scraped_at) OVER (PARTITION BY source, job_key) AS first_scraped,
                   max(scraped_at) OVER (PARTITION BY source, job_key) AS last_scraped
            FROM raw.job_postings
            {where}
        ) r
        LEFT JOIN (
            SELECT source, job_key,
                   (min(seen_on)::timestamp + interval '12 hours') AT TIME ZONE 'Africa/Nairobi' AS first_seen,
                   (max(seen_on)::timestamp + interval '12 hours') AT TIME ZONE 'Africa/Nairobi' AS last_seen
            FROM raw.sightings
            GROUP BY source, job_key
        ) s ON s.source = r.source AND s.job_key = r.job_key
        ORDER BY r.source, r.job_key, r.scraped_at DESC, r.id DESC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def transform_row(row: dict) -> tuple[dict, list[tuple[str, str]]]:
    a = get_adapter(row["source"])(row["payload"])
    title_raw = (a.get("title") or "").strip()
    title = clean_title(title_raw)
    desc = redact_contacts(html_to_text(a.get("description_html")))
    loc = map_location(a.get("location_text"))
    
    salary = (parse_salary_structured(a.get("base_salary"))
              or parse_salary_text(a.get("salary_text"))
              or parse_salary_text(desc) or {})
    company = clean_company(a.get("company"))
    c_norm, t_norm = company_norm(company), norm_text(title)
    dedup_key = None
    if t_norm and c_norm:  # hidden company => never merge
        key = f"{t_norm}|{c_norm}|{loc['county_code'] or ''}"
        dedup_key = hashlib.sha1(key.encode()).hexdigest()
    job_key = row["job_key"]
    posting = {
        "source": row["source"],
        "job_key": job_key,
        "raw_id": row["id"],
        "url": a.get("url") or (job_key if job_key.startswith("http") else None),
        "title_raw": title_raw or None,
        "title_clean": title or None,
        "title_norm": t_norm or None,
        "seniority": seniority(title),
        "company": company,
        "company_norm": c_norm,
        "location_raw": a.get("location_text") or None,
        "county": loc["county"],
        "county_code": loc["county_code"],
        "is_remote": bool(loc["is_remote"] or a.get("remote_hint")),
        "employment_type": a.get("employment_type"),
        "industry": a.get("industry"),
        "date_posted": parse_date(a.get("date_posted")),
        "valid_through": parse_date(a.get("valid_through")),
        "salary_currency": salary.get("currency"),
        "salary_min": salary.get("min"),
        "salary_max": salary.get("max"),
        "salary_period": salary.get("period"),
        "salary_min_monthly_kes": salary.get("min_monthly_kes"),
        "salary_max_monthly_kes": salary.get("max_monthly_kes"),
        "salary_source": salary.get("source"),
        "description_text": desc or None,
        "dedup_key": dedup_key,
        "first_seen_at": row["first_seen"],
        "last_seen_at": row["last_seen"],
    }
    skills = extract_skills(f"{title}. {a.get('skills_text', '')}. {desc}")
    return posting, skills


def profile(results) -> None:
    postings = [p for p, _ in results]
    n = len(postings)
    if not n:
        print("No rows to profile.")
        return

    def fill(label: str, count: int) -> None:
        print(f"  {label:<20}{count:>5}/{n}  ({100 * count / n:.0f}%)")

    print(f"\n=== Profile of {n} postings ===")
    fill("company", sum(1 for p in postings if p["company"]))
    fill("date_posted", sum(1 for p in postings if p["date_posted"]))
    fill("county mapped", sum(1 for p in postings if p["county"]))
    fill("remote", sum(1 for p in postings if p["is_remote"]))
    fill("salary", sum(1 for p in postings if p["salary_currency"]))
    fill("skills found", sum(1 for _, s in results if s))
    fill("dedup key made", sum(1 for p in postings if p["dedup_key"]))
    print("\nSeniority:", dict(Counter(p["seniority"] for p in postings)))
    print("Top skills:", Counter(name for _, s in results for name, _ in s).most_common(10))
    unmapped = Counter(p["location_raw"] for p in postings if not p["county"])
    print("Unmapped locations (add to TOWNS):", unmapped.most_common(10))
    print("\nSample:")
    for p in postings[:3]:
        print(f"  {p['title_raw']!r} -> {p['title_clean']!r} | {p['company']} | "
              f"{p['county']} | {p['salary_min_monthly_kes']}-{p['salary_max_monthly_kes']}")


def load(conn, results) -> None:
    postings = [p for p, _ in results]
    skill_rows = [(p["source"], p["job_key"], n, c) for p, skills in results for n, c in skills]
    with conn.cursor() as cur:
        cur.executemany(COUNTY_SQL, COUNTIES)  # reference data first (FK target)
        cur.executemany(UPSERT_SQL, postings)
        for source in sorted({p["source"] for p in postings}):
            cur.execute("DELETE FROM clean.job_skills WHERE source = %s", (source,))
        cur.executemany(SKILL_SQL, skill_rows)
        cur.execute(DEDUP_SQL)
        cur.execute("SELECT count(*), count(*) FILTER (WHERE is_duplicate) FROM clean.job_postings")
        total, dups = cur.fetchone()
    log.info("clean.job_postings: %d rows (%d flagged duplicate); %d skill rows written",
             total, dups, len(skill_rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", help="limit to a source (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="transform and profile, no writes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with get_conn() as conn:
        raw_rows = fetch_latest(conn, args.source)
        log.info("Fetched %d latest postings from raw", len(raw_rows))
        results = [transform_row(r) for r in raw_rows]
        profile(results)
        if args.dry_run:
            log.info("Dry run: nothing written")
            return
        load(conn, results)


if __name__ == "__main__":
    main()