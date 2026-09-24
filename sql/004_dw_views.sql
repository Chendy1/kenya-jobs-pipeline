-- Flat, de-duplicated view: what the dashboard (Phase 9) reads.
CREATE OR REPLACE VIEW dw.v_jobs AS
SELECT f.job_posting_key, f.source, f.url, f.title_clean, f.seniority,
       f.employment_type, f.industry,
       c.company_name, l.county_name, l.location_type, f.is_remote,
       d.full_date AS date_posted, d.cal_year, d.cal_month, d.iso_week,
       f.has_salary, f.salary_min_monthly_kes, f.salary_max_monthly_kes,
       f.salary_mid_monthly_kes, f.skill_count, f.days_advertised
FROM dw.fact_job_postings f
JOIN dw.dim_company  c ON c.company_key  = f.company_key
JOIN dw.dim_location l ON l.location_key = f.location_key
JOIN dw.dim_date     d ON d.date_key     = f.posted_date_key
WHERE NOT f.is_duplicate;

-- Phase 10: most in-demand skills.
CREATE OR REPLACE VIEW dw.v_top_skills AS
SELECT s.skill_name, s.category, count(*) AS postings,
       round(100.0 * count(*)
             / NULLIF((SELECT count(*) FROM dw.fact_job_postings WHERE NOT is_duplicate), 0), 1)
           AS pct_of_postings
FROM dw.bridge_job_skill b
JOIN dw.fact_job_postings f ON f.job_posting_key = b.job_posting_key
JOIN dw.dim_skill s         ON s.skill_key       = b.skill_key
WHERE NOT f.is_duplicate
GROUP BY s.skill_name, s.category
ORDER BY postings DESC, s.skill_name;

-- Phase 10: hiring by county and month (Unknown/Remote/Outside Kenya kept visible).
CREATE OR REPLACE VIEW dw.v_hiring_by_county AS
SELECT l.county_name, l.location_type, d.cal_year, d.cal_month, count(*) AS postings
FROM dw.fact_job_postings f
JOIN dw.dim_location l ON l.location_key = f.location_key
JOIN dw.dim_date d     ON d.date_key     = f.posted_date_key
WHERE NOT f.is_duplicate
GROUP BY l.county_name, l.location_type, d.cal_year, d.cal_month;

-- Phase 10: advertised salary bands by seniority (midpoints of bands, label them as such).
CREATE OR REPLACE VIEW dw.v_salary_by_seniority AS
SELECT seniority,
       count(*) AS postings_with_salary,
       round(avg(salary_mid_monthly_kes), 0) AS avg_band_midpoint_kes,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY salary_mid_monthly_kes))::numeric, 0)
           AS median_band_midpoint_kes
FROM dw.fact_job_postings
WHERE NOT is_duplicate AND has_salary
GROUP BY seniority
ORDER BY postings_with_salary DESC;

-- Phase 10: advertised window only. True observed lifetime needs Phase 7's sightings log.
CREATE OR REPLACE VIEW dw.v_advertised_window AS
SELECT source,
       count(*) AS postings,
       count(days_advertised) AS postings_with_window,
       round(avg(days_advertised), 1) AS avg_days_advertised
FROM dw.fact_job_postings
WHERE NOT is_duplicate
GROUP BY source;