CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.job_postings (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        TEXT        NOT NULL,
    job_key       TEXT        NOT NULL,
    content_hash  TEXT        NOT NULL,
    scraped_at    TIMESTAMPTZ NOT NULL,
    run_id        TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_job UNIQUE (source, job_key, content_hash)
);

CREATE INDEX IF NOT EXISTS ix_raw_job_lookup
    ON raw.job_postings (source, job_key, scraped_at DESC);

CREATE TABLE IF NOT EXISTS raw.ingest_runs (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           TEXT        NOT NULL,
    source           TEXT        NOT NULL,
    raw_key          TEXT,
    records_seen     INT         NOT NULL,
    records_inserted INT         NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
