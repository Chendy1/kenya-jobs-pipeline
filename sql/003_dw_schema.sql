CREATE SCHEMA IF NOT EXISTS dw;

-- Map a date to its dim_date key; NULL or out-of-range dates become the Unknown member (-1).
CREATE OR REPLACE FUNCTION dw.date_key(d date) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN d BETWEEN DATE '2000-01-01' AND DATE '2040-12-31'
                THEN to_char(d, 'YYYYMMDD')::int
                ELSE -1 END
$$;

CREATE TABLE IF NOT EXISTS dw.dim_date (
    date_key     INT PRIMARY KEY,              -- 20260924; -1 = Unknown
    full_date    DATE UNIQUE,
    cal_year     SMALLINT,
    cal_quarter  SMALLINT,
    cal_month    SMALLINT,
    month_name   TEXT,
    iso_week     SMALLINT,
    day_of_month SMALLINT,
    iso_dow      SMALLINT,                     -- 1 = Monday ... 7 = Sunday
    day_name     TEXT,
    is_weekend   BOOLEAN
);

CREATE TABLE IF NOT EXISTS dw.dim_location (
    location_key  SMALLINT PRIMARY KEY,        -- county_code for counties; -1/-2/-3 special
    location_type TEXT NOT NULL
        CHECK (location_type IN ('county', 'unknown', 'remote', 'outside_kenya')),
    county_code   SMALLINT REFERENCES ref.counties (county_code),
    county_name   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.dim_company (
    company_key  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_norm TEXT NOT NULL UNIQUE,         -- business key ('(unknown)' for the -1 member)
    company_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.dim_skill (
    skill_key  INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    skill_name TEXT NOT NULL UNIQUE,
    category   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dw.fact_job_postings (
    job_posting_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source                 TEXT     NOT NULL,
    job_key                TEXT     NOT NULL,
    company_key            BIGINT   NOT NULL REFERENCES dw.dim_company (company_key),
    location_key           SMALLINT NOT NULL REFERENCES dw.dim_location (location_key),
    posted_date_key        INT      NOT NULL REFERENCES dw.dim_date (date_key),
    valid_through_date_key INT      NOT NULL REFERENCES dw.dim_date (date_key),
    first_seen_date_key    INT      NOT NULL REFERENCES dw.dim_date (date_key),
    last_seen_date_key     INT      NOT NULL REFERENCES dw.dim_date (date_key),
    title_clean            TEXT,
    seniority              TEXT,
    employment_type        TEXT,
    industry               TEXT,
    url                    TEXT,
    is_remote              BOOLEAN  NOT NULL,
    is_duplicate           BOOLEAN  NOT NULL,
    has_salary             BOOLEAN  NOT NULL,
    salary_min_monthly_kes NUMERIC(14,2),
    salary_max_monthly_kes NUMERIC(14,2),
    salary_mid_monthly_kes NUMERIC(14,2),      -- midpoint of the advertised band, not exact pay
    salary_source          TEXT,
    skill_count            SMALLINT NOT NULL DEFAULT 0,
    days_advertised        INT,                -- valid_through - date_posted, when both exist
    loaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fact_job UNIQUE (source, job_key)
);

CREATE INDEX IF NOT EXISTS ix_fact_location ON dw.fact_job_postings (location_key);
CREATE INDEX IF NOT EXISTS ix_fact_company  ON dw.fact_job_postings (company_key);
CREATE INDEX IF NOT EXISTS ix_fact_posted   ON dw.fact_job_postings (posted_date_key);

CREATE TABLE IF NOT EXISTS dw.bridge_job_skill (
    job_posting_key BIGINT NOT NULL
        REFERENCES dw.fact_job_postings (job_posting_key) ON DELETE CASCADE,
    skill_key       INT    NOT NULL REFERENCES dw.dim_skill (skill_key),
    PRIMARY KEY (job_posting_key, skill_key)
);

CREATE INDEX IF NOT EXISTS ix_bridge_skill ON dw.bridge_job_skill (skill_key);