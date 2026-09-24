# Star schema

```mermaid
erDiagram
    FACT_JOB_POSTINGS }o--|| DIM_COMPANY : company_key
    FACT_JOB_POSTINGS }o--|| DIM_LOCATION : location_key
    FACT_JOB_POSTINGS }o--|| DIM_DATE : "posted / valid_through / first_seen / last_seen"
    FACT_JOB_POSTINGS ||--o{ BRIDGE_JOB_SKILL : has
    DIM_SKILL ||--o{ BRIDGE_JOB_SKILL : appears_in
```

Grain: one row per unique job posting (source, job_key). Duplicates are flagged, not deleted.
Unknown members: company -1; location -1 (unspecified), -2 (remote), -3 (outside Kenya); date -1.