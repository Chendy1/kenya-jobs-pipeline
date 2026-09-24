-- Phase 5 load: clean.* -> dw.*. Idempotent: safe to run repeatedly.

-- 1. dim_date: 2000-01-01 .. 2040-12-31, plus the Unknown member.
INSERT INTO dw.dim_date (date_key, full_date, cal_year, cal_quarter, cal_month, month_name,
                         iso_week, day_of_month, iso_dow, day_name, is_weekend)
SELECT to_char(d, 'YYYYMMDD')::int, d,
       extract(year FROM d)::smallint, extract(quarter FROM d)::smallint,
       extract(month FROM d)::smallint, trim(to_char(d, 'Month')),
       extract(week FROM d)::smallint, extract(day FROM d)::smallint,
       extract(isodow FROM d)::smallint, trim(to_char(d, 'Day')),
       extract(isodow FROM d) >= 6
FROM (SELECT DATE '2000-01-01' + n AS d FROM generate_series(0, 14975) AS n) t
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO dw.dim_date (date_key, month_name, day_name)
VALUES (-1, 'Unknown', 'Unknown')
ON CONFLICT (date_key) DO NOTHING;

-- 2. dim_location: 47 counties (from ref.counties) + 3 special members.
INSERT INTO dw.dim_location (location_key, location_type, county_code, county_name)
SELECT county_code, 'county', county_code, county_name FROM ref.counties
ON CONFLICT (location_key) DO UPDATE SET county_name = EXCLUDED.county_name;

INSERT INTO dw.dim_location (location_key, location_type, county_code, county_name)
VALUES (-1, 'unknown', NULL, 'Unknown'),
       (-2, 'remote', NULL, 'Remote'),
       (-3, 'outside_kenya', NULL, 'Outside Kenya')
ON CONFLICT (location_key) DO NOTHING;

-- 3. dim_company: Unknown member + one row per normalised company (latest display name wins).
INSERT INTO dw.dim_company (company_key, company_norm, company_name)
OVERRIDING SYSTEM VALUE
VALUES (-1, '(unknown)', 'Unknown / confidential')
ON CONFLICT DO NOTHING;

INSERT INTO dw.dim_company (company_norm, company_name)
SELECT DISTINCT ON (company_norm) company_norm, company
FROM clean.job_postings
WHERE company_norm IS NOT NULL
ORDER BY company_norm, last_seen_at DESC NULLS LAST, company
ON CONFLICT (company_norm) DO UPDATE SET company_name = EXCLUDED.company_name;

-- 4. dim_skill
INSERT INTO dw.dim_skill (skill_name, category)
SELECT DISTINCT ON (skill) skill, category
FROM clean.job_skills
ORDER BY skill, category
ON CONFLICT (skill_name) DO UPDATE SET category = EXCLUDED.category;

-- 5. fact: upsert every clean posting, then remove any that no longer exist in clean.
INSERT INTO dw.fact_job_postings (
    source, job_key, company_key, location_key,
    posted_date_key, valid_through_date_key, first_seen_date_key, last_seen_date_key,
    title_clean, seniority, employment_type, industry, url,
    is_remote, is_duplicate, has_salary,
    salary_min_monthly_kes, salary_max_monthly_kes, salary_mid_monthly_kes, salary_source,
    skill_count, days_advertised
)
SELECT
    c.source, c.job_key,
    COALESCE(dc.company_key, -1),
    CASE WHEN c.county_code IS NOT NULL THEN c.county_code
         WHEN c.location_raw ILIKE '%outside kenya%' THEN -3
         WHEN c.is_remote THEN -2
         ELSE -1 END,
    dw.date_key(c.date_posted),
    dw.date_key(c.valid_through),
    dw.date_key((c.first_seen_at AT TIME ZONE 'Africa/Nairobi')::date),
    dw.date_key((c.last_seen_at  AT TIME ZONE 'Africa/Nairobi')::date),
    c.title_clean, c.seniority, c.employment_type, c.industry, c.url,
    c.is_remote, c.is_duplicate, c.salary_min_monthly_kes IS NOT NULL,
    c.salary_min_monthly_kes, c.salary_max_monthly_kes,
    (c.salary_min_monthly_kes + c.salary_max_monthly_kes) / 2,
    c.salary_source,
    COALESCE(sk.n, 0),
    CASE WHEN c.valid_through >= c.date_posted THEN c.valid_through - c.date_posted END
FROM clean.job_postings c
LEFT JOIN dw.dim_company dc ON dc.company_norm = c.company_norm
LEFT JOIN (SELECT source, job_key, count(*) AS n
           FROM clean.job_skills GROUP BY source, job_key) sk
       ON sk.source = c.source AND sk.job_key = c.job_key
ON CONFLICT (source, job_key) DO UPDATE SET
    company_key = EXCLUDED.company_key,
    location_key = EXCLUDED.location_key,
    posted_date_key = EXCLUDED.posted_date_key,
    valid_through_date_key = EXCLUDED.valid_through_date_key,
    first_seen_date_key = EXCLUDED.first_seen_date_key,
    last_seen_date_key = EXCLUDED.last_seen_date_key,
    title_clean = EXCLUDED.title_clean,
    seniority = EXCLUDED.seniority,
    employment_type = EXCLUDED.employment_type,
    industry = EXCLUDED.industry,
    url = EXCLUDED.url,
    is_remote = EXCLUDED.is_remote,
    is_duplicate = EXCLUDED.is_duplicate,
    has_salary = EXCLUDED.has_salary,
    salary_min_monthly_kes = EXCLUDED.salary_min_monthly_kes,
    salary_max_monthly_kes = EXCLUDED.salary_max_monthly_kes,
    salary_mid_monthly_kes = EXCLUDED.salary_mid_monthly_kes,
    salary_source = EXCLUDED.salary_source,
    skill_count = EXCLUDED.skill_count,
    days_advertised = EXCLUDED.days_advertised,
    loaded_at = now();

DELETE FROM dw.fact_job_postings f
WHERE NOT EXISTS (SELECT 1 FROM clean.job_postings c
                  WHERE c.source = f.source AND c.job_key = f.job_key);

-- 6. bridge: full refresh (it has no identity of its own).
DELETE FROM dw.bridge_job_skill;

INSERT INTO dw.bridge_job_skill (job_posting_key, skill_key)
SELECT f.job_posting_key, s.skill_key
FROM clean.job_skills js
JOIN dw.fact_job_postings f ON f.source = js.source AND f.job_key = js.job_key
JOIN dw.dim_skill s         ON s.skill_name = js.skill
ON CONFLICT DO NOTHING;