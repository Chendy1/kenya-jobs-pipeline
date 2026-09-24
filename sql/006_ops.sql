CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.dq_results (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    check_name TEXT    NOT NULL,
    layer      TEXT    NOT NULL,
    severity   TEXT    NOT NULL,
    violations BIGINT  NOT NULL,
    total      BIGINT  NOT NULL,
    passed     BOOLEAN NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS ix_dq_results_run   ON ops.dq_results (run_at DESC);
CREATE INDEX IF NOT EXISTS ix_dq_results_check ON ops.dq_results (check_name, run_at DESC);

CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'warnings', 'failed', 'crashed')),
    summary     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.alert_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    level       TEXT NOT NULL,
    subject     TEXT NOT NULL,
    channels    TEXT NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_alert_fp ON ops.alert_log (fingerprint, sent_at DESC);

-- Latest result per check: what a Phase 9 "pipeline health" page reads.
CREATE OR REPLACE VIEW ops.v_latest_dq AS
SELECT DISTINCT ON (check_name)
       check_name, layer, severity, passed, violations, total, detail, run_at
FROM ops.dq_results
ORDER BY check_name, run_at DESC;