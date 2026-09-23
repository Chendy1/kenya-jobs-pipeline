CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS ref.counties (
    county_code SMALLINT PRIMARY KEY,
    county_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS clean.job_postings (
    source                  TEXT NOT NULL,
    job_key                 TEXT NOT NULL,
    raw_id                  BIGINT,
    url                     TEXT,
    title_raw               TEXT,
    title_clean             TEXT,
    title_norm              TEXT,
    seniority               TEXT,
    company                 TEXT,
    company_norm            TEXT,
    location_raw            TEXT,
    county                  TEXT,
    county_code             SMALLINT REFERENCES ref.counties (county_code),
    is_remote               BOOLEAN NOT NULL DEFAULT FALSE,
    employment_type         TEXT,
    industry                TEXT,
    date_posted             DATE,
    valid_through           DATE,
    salary_currency         TEXT,
    salary_min              NUMERIC(14,2),
    salary_max              NUMERIC(14,2),
    salary_period           TEXT,
    salary_min_monthly_kes  NUMERIC(14,2),
    salary_max_monthly_kes  NUMERIC(14,2),
    salary_source           TEXT,
    description_text        TEXT,
    dedup_key               TEXT,
    is_duplicate            BOOLEAN NOT NULL DEFAULT FALSE,
    canonical_source        TEXT,
    canonical_job_key       TEXT,
    first_seen_at           TIMESTAMPTZ,
    last_seen_at            TIMESTAMPTZ,
    transformed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, job_key)
);

CREATE INDEX IF NOT EXISTS ix_clean_county ON clean.job_postings (county_code);
CREATE INDEX IF NOT EXISTS ix_clean_dedup  ON clean.job_postings (dedup_key);
CREATE INDEX IF NOT EXISTS ix_clean_posted ON clean.job_postings (date_posted);

CREATE TABLE IF NOT EXISTS clean.job_skills (
    source   TEXT NOT NULL,
    job_key  TEXT NOT NULL,
    skill    TEXT NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (source, job_key, skill),
    FOREIGN KEY (source, job_key)
        REFERENCES clean.job_postings (source, job_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_skills_skill ON clean.job_skills (skill);