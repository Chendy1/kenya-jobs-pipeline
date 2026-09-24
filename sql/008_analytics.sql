-- ================= statistics helpers =================
-- Wilson score interval for a proportion k/n (95%). Returned as a fraction between 0 and 1.
CREATE OR REPLACE FUNCTION dw.wilson_low(k numeric, n numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN n IS NULL OR n <= 0 THEN NULL ELSE
        GREATEST(0::numeric,
            ((k / n + 1.96^2 / (2 * n))
             - 1.96 * sqrt((k / n) * (1 - k / n) / n + 1.96^2 / (4 * n^2)))
            / (1 + 1.96^2 / n))
    END
$$;

CREATE OR REPLACE FUNCTION dw.wilson_high(k numeric, n numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN n IS NULL OR n <= 0 THEN NULL ELSE
        LEAST(1::numeric,
            ((k / n + 1.96^2 / (2 * n))
             + 1.96 * sqrt((k / n) * (1 - k / n) / n + 1.96^2 / (4 * n^2)))
            / (1 + 1.96^2 / n))
    END
$$;

-- Kaplan-Meier survival curve. durations[i] = days observed, events[i] = TRUE if the posting left
-- the listing, FALSE if it was still visible (censored). Returns one row per distinct duration.
CREATE OR REPLACE FUNCTION dw.km_survival(durations int[], events boolean[])
RETURNS TABLE (t int, at_risk int, n_events int, survival numeric)
LANGUAGE sql IMMUTABLE AS $$
    WITH obs AS (
        SELECT u.d AS t, u.e AS event FROM unnest(durations, events) AS u(d, e)
    ), steps AS (
        SELECT t, count(*) AS c, count(*) FILTER (WHERE event) AS d FROM obs GROUP BY t
    ), risk AS (
        SELECT t, d, sum(c) OVER (ORDER BY t DESC) AS n FROM steps      -- subjects with duration >= t
    )
    SELECT t,
           n::int,
           d::int,
           exp(sum(ln(GREATEST(1 - d::numeric / n, 0.000000001))) OVER (ORDER BY t))
    FROM risk
    ORDER BY t
$$;

-- ================= one base view: public sources only =================
CREATE OR REPLACE VIEW dw.v_analytics_base AS
SELECT p.job_posting_key, p.source, p.title, p.company_name, p.county_name, p.location_type,
       p.is_remote, p.date_posted, p.seniority, p.category, p.has_salary, p.salary_mid_kes,
       p.skills, f.days_advertised,
       d1.full_date AS first_seen,
       d2.full_date AS last_seen
FROM dw.v_public_jobs p
JOIN dw.fact_job_postings f ON f.job_posting_key = p.job_posting_key
JOIN dw.dim_date d1 ON d1.date_key = f.first_seen_date_key
JOIN dw.dim_date d2 ON d2.date_key = f.last_seen_date_key;

-- ================= coverage: what the data can and cannot say =================
CREATE OR REPLACE VIEW dw.v_coverage_sources AS
SELECT source,
       count(*)::int                                                       AS postings,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)                  AS share_pct,
       min(first_seen)                                                     AS first_crawl,
       max(last_seen)                                                      AS last_crawl,
       (max(last_seen) - min(first_seen) + 1)::int                         AS history_days,
       min(date_posted)                                                    AS oldest_posted,
       max(date_posted)                                                    AS newest_posted,
       round(100.0 * count(*) FILTER (WHERE has_salary) / count(*), 1)     AS pct_with_salary,
       round(100.0 * count(*) FILTER (WHERE location_type = 'county') / count(*), 1) AS pct_with_county,
       count(*) FILTER (WHERE category IN ('Data & Analytics', 'Software & IT'))::int AS tech_postings
FROM dw.v_analytics_base
GROUP BY source;

CREATE OR REPLACE VIEW dw.v_coverage_overall AS
SELECT count(*)::int                                   AS postings,
       count(DISTINCT source)::int                     AS sources,
       (max(last_seen) - min(first_seen) + 1)::int     AS history_days,
       min(first_seen)                                 AS first_crawl,
       max(last_seen)                                  AS last_crawl,
       count(*) FILTER (WHERE category IN ('Data & Analytics', 'Software & IT'))::int AS tech_postings,
       count(*) FILTER (WHERE location_type = 'county')::int                          AS county_located
FROM dw.v_analytics_base;

-- ================= skills: share of Data and Software postings, with intervals =================
CREATE OR REPLACE VIEW dw.v_skill_demand AS
WITH tech AS (
    SELECT * FROM dw.v_analytics_base WHERE category IN ('Data & Analytics', 'Software & IT')
), totals AS (
    SELECT source, count(*) AS n FROM tech GROUP BY source HAVING count(*) >= 10
), mentions AS (
    SELECT t.source, u.skill, count(*) AS postings
    FROM tech t CROSS JOIN LATERAL unnest(t.skills) AS u(skill)
    GROUP BY t.source, u.skill
), skill_names AS (
    SELECT DISTINCT skill FROM mentions
), grid AS (
    SELECT k.skill, o.source, o.n, COALESCE(m.postings, 0) AS postings
    FROM skill_names k
    CROSS JOIN totals o
    LEFT JOIN mentions m ON m.skill = k.skill AND m.source = o.source
)
SELECT g.skill                                                     AS skill_name,
       ds.category                                                 AS skill_category,
       sum(g.postings)::int                                        AS postings,
       sum(g.n)::int                                               AS n_tech,
       round(100.0 * sum(g.postings) / sum(g.n), 1)                AS pooled_pct,
       round(100 * dw.wilson_low(sum(g.postings), sum(g.n)), 1)    AS ci_low_pct,
       round(100 * dw.wilson_high(sum(g.postings), sum(g.n)), 1)   AS ci_high_pct,
       round(avg(100.0 * g.postings / g.n), 1)                     AS balanced_pct,
       (count(*) FILTER (WHERE g.postings > 0))::int               AS sources_mentioning,
       count(*)::int                                               AS sources_total,
       sum(g.postings) >= 5                                        AS reliable
FROM grid g
LEFT JOIN dw.dim_skill ds ON ds.skill_name = g.skill
GROUP BY g.skill, ds.category;

-- ================= counties =================
CREATE OR REPLACE VIEW dw.v_county_summary AS
WITH located AS (
    SELECT * FROM dw.v_analytics_base WHERE location_type = 'county'
), total AS (
    SELECT count(*) AS n FROM located
)
SELECT l.county_name,
       count(*)::int                                                         AS postings,
       (SELECT n FROM total)::int                                            AS n_located,
       round(100.0 * count(*) / (SELECT n FROM total), 1)                    AS share_pct,
       round(100 * dw.wilson_low(count(*), (SELECT n FROM total)), 1)        AS ci_low_pct,
       round(100 * dw.wilson_high(count(*), (SELECT n FROM total)), 1)       AS ci_high_pct,
       count(DISTINCT l.source)::int                                         AS sources,
       (count(*) FILTER (WHERE l.has_salary))::int                           AS n_salary,
       CASE WHEN count(*) FILTER (WHERE l.has_salary) >= 5
            THEN round((percentile_cont(0.5) WITHIN GROUP (ORDER BY l.salary_mid_kes)
                        FILTER (WHERE l.has_salary))::numeric, 0)
       END                                                                   AS median_salary_band_mid_kes,
       count(*) >= 10                                                        AS reliable
FROM located l
GROUP BY l.county_name;

-- ================= weekly new postings (only postings posted after we started watching) ==========
CREATE OR REPLACE VIEW dw.v_weekly_new_postings AS
WITH crawl AS (
    SELECT source, min(first_seen) AS crawl_start, max(last_seen) AS crawl_end
    FROM dw.v_analytics_base GROUP BY source
)
SELECT date_trunc('week', b.date_posted)::date AS week_start,
       b.source, b.county_name, b.location_type,
       count(*)::int AS postings,
       (date_trunc('week', b.date_posted)::date >= c.crawl_start
        AND date_trunc('week', b.date_posted)::date + 6 <= c.crawl_end) AS week_complete
FROM dw.v_analytics_base b
JOIN crawl c ON c.source = b.source
WHERE b.date_posted >= c.crawl_start
GROUP BY 1, 2, 3, 4, c.crawl_start, c.crawl_end;

-- ================= advertised window: closing date minus posted date (no censoring issue) =========
CREATE OR REPLACE VIEW dw.v_advertised_window_stats AS
SELECT source,
       count(*)::int                                          AS postings,
       count(days_advertised)::int                            AS with_window,
       round(100.0 * count(days_advertised) / count(*), 1)    AS pct_with_window,
       round((percentile_cont(0.25) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1) AS p25_days,
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1) AS median_days,
       round((percentile_cont(0.75) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1) AS p75_days
FROM dw.v_analytics_base
GROUP BY source
UNION ALL
SELECT 'all',
       count(*)::int,
       count(days_advertised)::int,
       round(100.0 * count(days_advertised) / NULLIF(count(*), 0), 1),
       round((percentile_cont(0.25) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1),
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1),
       round((percentile_cont(0.75) WITHIN GROUP (ORDER BY days_advertised))::numeric, 1)
FROM dw.v_analytics_base;

-- ================= crawl depth: how many days of postings does one crawl day actually cover? ======
CREATE OR REPLACE VIEW dw.v_feed_depth AS
SELECT s.source, s.seen_on,
       count(*)::int                             AS postings_seen,
       min(d.full_date)                          AS oldest_posted,
       max(d.full_date)                          AS newest_posted,
       (max(d.full_date) - min(d.full_date))::int AS window_days
FROM raw.sightings s
JOIN dw.fact_job_postings f ON f.source = s.source AND f.job_key = s.job_key
JOIN dw.dim_date d          ON d.date_key = f.posted_date_key
JOIN ref.source_publishing sp ON sp.source = s.source AND sp.publishable
GROUP BY s.source, s.seen_on;

-- ================= observed lifetimes (right-censored) =================
-- Cohort: postings posted on or after the day we started watching that source.
-- left_listing: at least 3 collection days have passed since we last saw the posting.
CREATE OR REPLACE VIEW dw.v_lifetime_observations AS
WITH crawl_days AS (
    SELECT source, seen_on FROM raw.sightings GROUP BY source, seen_on
), crawl_start AS (
    SELECT source, min(first_seen) AS started FROM dw.v_analytics_base GROUP BY source
)
SELECT b.source, b.job_posting_key,
       GREATEST(b.last_seen - b.date_posted + 1, 1) AS duration_days,
       (SELECT count(*) FROM crawl_days c
        WHERE c.source = b.source AND c.seen_on > b.last_seen) >= 3 AS left_listing
FROM dw.v_analytics_base b
JOIN crawl_start s ON s.source = b.source
WHERE b.date_posted >= s.started;

CREATE OR REPLACE VIEW dw.v_lifetime_km AS
SELECT g.source, k.t AS age_days, k.at_risk, k.n_events, round(k.survival, 4) AS survival
FROM (
    SELECT source,
           array_agg(duration_days ORDER BY job_posting_key) AS durations,
           array_agg(left_listing  ORDER BY job_posting_key) AS events
    FROM dw.v_lifetime_observations
    GROUP BY source
) g
CROSS JOIN LATERAL dw.km_survival(g.durations, g.events) k;

CREATE OR REPLACE VIEW dw.v_lifetime_summary AS
WITH obs AS (
    SELECT source, count(*) AS n, count(*) FILTER (WHERE left_listing) AS events
    FROM dw.v_lifetime_observations GROUP BY source
), med AS (
    SELECT source, min(age_days) AS median_days FROM dw.v_lifetime_km WHERE survival <= 0.5 GROUP BY source
), depth AS (
    SELECT source, percentile_cont(0.5) WITHIN GROUP (ORDER BY window_days) AS feed_window_days
    FROM dw.v_feed_depth GROUP BY source
)
SELECT o.source,
       o.n::int                         AS cohort_postings,
       o.events::int                    AS left_listing,
       (o.n - o.events)::int            AS still_visible,
       m.median_days,
       round(d.feed_window_days::numeric, 1) AS feed_window_days,
       (o.events >= 30 AND m.median_days IS NOT NULL
        AND m.median_days > 1.5 * d.feed_window_days) AS trustworthy
FROM obs o
LEFT JOIN med m   ON m.source = o.source
LEFT JOIN depth d ON d.source = o.source;