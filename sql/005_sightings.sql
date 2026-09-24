-- One row per (posting, day) on which we saw it. Drives lifetimes and incremental fetching.
CREATE TABLE IF NOT EXISTS raw.sightings (
    source   TEXT    NOT NULL,
    job_key  TEXT    NOT NULL,
    seen_on  DATE    NOT NULL,                 -- Nairobi calendar date
    fetched  BOOLEAN NOT NULL DEFAULT FALSE,   -- did we download the full posting that day?
    PRIMARY KEY (source, job_key, seen_on)
);

CREATE INDEX IF NOT EXISTS ix_sightings_recent ON raw.sightings (source, seen_on);

-- Seed from history: every raw version was seen and fetched on its scrape day. Idempotent.
INSERT INTO raw.sightings (source, job_key, seen_on, fetched)
SELECT DISTINCT source, job_key, (scraped_at AT TIME ZONE 'Africa/Nairobi')::date, TRUE
FROM raw.job_postings
ON CONFLICT DO NOTHING;

-- Observed window per posting. A LOWER BOUND on real lifetime: sources only show newer postings.
CREATE OR REPLACE VIEW dw.v_posting_lifetimes AS
WITH latest AS (
    SELECT f.source, max(d.full_date) AS source_last_seen
    FROM dw.fact_job_postings f
    JOIN dw.dim_date d ON d.date_key = f.last_seen_date_key
    GROUP BY f.source
)
SELECT f.source, f.job_key, f.title_clean,
       d1.full_date AS first_seen,
       d2.full_date AS last_seen,
       d2.full_date - d1.full_date AS days_observed,
       d2.full_date >= l.source_last_seen - 3 AS seen_recently
FROM dw.fact_job_postings f
JOIN dw.dim_date d1 ON d1.date_key = f.first_seen_date_key
JOIN dw.dim_date d2 ON d2.date_key = f.last_seen_date_key
JOIN latest l       ON l.source = f.source
WHERE NOT f.is_duplicate;