-- ============ category rules (edit by inserting rows with priority >= 200) ============
CREATE TABLE IF NOT EXISTS ref.category_rules (
    priority       INT  PRIMARY KEY,
    category       TEXT NOT NULL,
    title_regex    TEXT,
    industry_regex TEXT
);

INSERT INTO ref.category_rules (priority, category, title_regex, industry_regex) VALUES
 (10,  'Data & Analytics',
  '\y(data (analyst|analytics|engineer|scientist|architect|steward|manager|warehouse\w*)|analytics|business intelligence|bi (developer|analyst|engineer)|statistician|machine learning|ml engineer|ai engineer)\y',
  NULL),
 (20,  'Software & IT',
  '\y(software|developer|programmer|devops|sre|full[- ]?stack|front[- ]?end|back[- ]?end|web (developer|designer)|mobile (developer|app\w*)|qa engineer|tester|cyber ?security|network (engineer|administrator)|systems? (administrator|engineer|analyst)|it (support|officer|manager|technician|specialist)|ict|helpdesk|help desk|cloud|database administrator|dba|infrastructure|technical support)\y',
  '\y(ict|it|computer|information technology|information and communications? technology|software|telecom\w*)\y'),
 (30,  'Sales & Marketing',
  '\y(sales|dealer|marketer|marketing|business development|brand|social media|digital marketing|merchandis\w*|key accounts?|account (manager|executive)|customer acquisition|promoter|telesales)\y',
  '\y(sales|marketing|advertising|public relations)\y'),
 (40,  'Finance & Accounting',
  '\y(account(ant|ants|ing|s)?|finance|financial|audit\w*|tax|treasury|bookkeep\w*|payroll|credit (analyst|controller|officer)|cashier|budget\w*|actuar\w*)\y',
  '\y(accounting|finance|banking|audit\w*|insurance|financial services)\y'),
 (50,  'Human Resources',
  '\y(human resources?|hr|recruit\w*|talent|people (and culture|partner)|learning and development|l&d|training officer)\y',
  '\y(human resources?|hr|recruitment)\y'),
 (60,  'Engineering & Construction',
  '\y(engineer\w*|civil|mechanical|electrical|electrician|technician|surveyor|architect\w*|foreman|site (manager|supervisor|engineer)|construction|plumber|welder|mason|artisan|draughts\w*|structural)\y',
  '\y(engineering|construction|building|architecture)\y'),
 (70,  'Health & Medical',
  '\y(nurse|nursing|doctor|clinical|clinician|medical|pharmac\w*|laborator\w*|physician|dentist|midwife|paramedic|radiograph\w*|nutritionist|veterinar\w*|health (officer|worker|records|coordinator))\y',
  '\y(medical|health\w*|pharmac\w*|nursing|healthcare)\y'),
 (80,  'Hospitality & Tourism',
  '\y(chef|cook|waiter|waitress|barista|bartender|hotel|hospitality|restaurant|kitchen|housekeep\w*|front office|receptionist|concierge|tour (guide|operator)|travel|safari|lodge|service crew|pizzaiolo|baker|catering)\y',
  '\y(hospitality|hotel\w*|tourism|catering|travel|restaurant\w*)\y'),
 (90,  'Logistics & Supply Chain',
  '\y(driver|logistics|supply chain|warehouse\w*|procurement|stores?|fleet|transport\w*|shipping|clearing|forwarding|dispatch\w*|rider|delivery|courier|inventory|purchasing|distribution)\y',
  '\y(logistics|transport\w*|supply chain|procurement|shipping|distribution)\y'),
 (100, 'Education & Training',
  '\y(teacher|lecturer|tutor|principal|headteacher|head teacher|school|academic|instructor|trainer|professor|librarian|education|curriculum)\y',
  '\y(education|teaching|training|academic\w*)\y'),
 (105, 'Agriculture & Environment',
  '\y(agronom\w*|agricultur\w*|farm\w*|horticultur\w*|livestock|forest\w*|environment\w*|extension officer|crop|fisheries|agribusiness)\y',
  '\y(agricultur\w*|agribusiness|environment\w*|farming|forestry)\y'),
 (110, 'NGO & Development',
  '\y(programme|program|project (officer|coordinator|manager|assistant)|monitoring|evaluation|m&e|humanitarian|protection|livelihoods?|grants?|advocacy|community (mobili[sz]er|development)|field officer|consultan\w*)\y',
  '\y(ngo|non[- ]?profit|development|humanitarian|charity|social work\w*)\y'),
 (115, 'Legal & Compliance',
  '\y(legal|lawyer|advocate|paralegal|compliance|company secretary|counsel|risk)\y',
  '\y(legal|law|compliance)\y'),
 (120, 'Admin & Support',
  '\y(admin\w*|secretary|receptionist|clerk|office (assistant|manager|administrator)|personal assistant|executive assistant|data entry|virtual assistant|customer (service|care|support|experience)|call cent(re|er)|front desk|assistant|support officer)\y',
  '\y(administration|secretarial|customer service|clerical)\y')
ON CONFLICT (priority) DO UPDATE SET
    category = EXCLUDED.category,
    title_regex = EXCLUDED.title_regex,
    industry_regex = EXCLUDED.industry_regex;

-- A title match beats an industry match; then the lowest priority number wins.
CREATE OR REPLACE FUNCTION ref.classify_category(p_title text, p_industry text)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT COALESCE((
        SELECT r.category
        FROM ref.category_rules r
        WHERE p_title ~* r.title_regex OR p_industry ~* r.industry_regex
        ORDER BY (p_title ~* r.title_regex) DESC NULLS LAST, r.priority
        LIMIT 1
    ), 'Other')
$$;

-- ============ what may be shown publicly (data, not code; unlisted sources fail safe) ============
CREATE TABLE IF NOT EXISTS ref.source_publishing (
    source      TEXT PRIMARY KEY,
    publishable BOOLEAN NOT NULL,
    note        TEXT
);

-- DO NOTHING: your manual changes (for example after written consent) survive re-runs.
INSERT INTO ref.source_publishing (source, publishable, note) VALUES
 ('myjobmag',       TRUE,  'robots.txt allows; no automation clause in the 2012 terms; titles and links only'),
 ('reliefweb',      TRUE,  'official API; link back; no descriptions'),
 ('jsearch',        TRUE,  'licensed API; link back; no descriptions'),
 ('jooble',         TRUE,  'official API; link back'),
 ('brightermonday', FALSE, 'terms need written consent for scraping and limit use to personal non-commercial: private only')
ON CONFLICT (source) DO NOTHING;

-- ============ job views ============
CREATE OR REPLACE VIEW dw.v_jobs_enriched AS
SELECT f.job_posting_key,
       f.source,
       f.url,
       f.title_clean                                    AS title,
       c.company_name,
       l.county_name,
       l.location_type,
       f.is_remote,
       d.full_date                                      AS date_posted,
       f.seniority,
       ref.classify_category(f.title_clean, f.industry) AS category,
       f.industry,
       f.employment_type,
       f.has_salary,
       round(f.salary_min_monthly_kes)::int             AS salary_min_kes,
       round(f.salary_max_monthly_kes)::int             AS salary_max_kes,
       round(f.salary_mid_monthly_kes)::int             AS salary_mid_kes,
       f.salary_source,
       ARRAY(SELECT s.skill_name
             FROM dw.bridge_job_skill b
             JOIN dw.dim_skill s ON s.skill_key = b.skill_key
             WHERE b.job_posting_key = f.job_posting_key
             ORDER BY s.skill_name)                     AS skills,
       COALESCE(sp.publishable, FALSE)                  AS publishable
FROM dw.fact_job_postings f
JOIN dw.dim_company  c ON c.company_key  = f.company_key
JOIN dw.dim_location l ON l.location_key = f.location_key
JOIN dw.dim_date     d ON d.date_key     = f.posted_date_key
LEFT JOIN ref.source_publishing sp ON sp.source = f.source
WHERE NOT f.is_duplicate;

CREATE OR REPLACE VIEW dw.v_public_jobs AS
SELECT * FROM dw.v_jobs_enriched WHERE publishable;

-- ============ pipeline-health views (no error text, safe to show publicly) ============
CREATE OR REPLACE VIEW ops.v_public_dq_summary AS
SELECT layer,
       count(*)                                                     AS checks,
       count(*) FILTER (WHERE passed)                               AS passed,
       count(*) FILTER (WHERE NOT passed AND severity = 'error')    AS failing_errors,
       count(*) FILTER (WHERE NOT passed AND severity = 'warn')     AS failing_warnings,
       max(run_at)                                                  AS last_checked
FROM ops.v_latest_dq
GROUP BY layer;

CREATE OR REPLACE VIEW ops.v_public_runs AS
SELECT id, started_at, finished_at,
       extract(epoch FROM finished_at - started_at)::int AS duration_s,
       status
FROM ops.pipeline_runs
ORDER BY id DESC
LIMIT 30;

CREATE OR REPLACE VIEW ops.v_public_source_freshness AS
SELECT s.source,
       max(s.seen_on)              AS last_seen_on,
       count(DISTINCT s.job_key)   AS postings_seen_total
FROM raw.sightings s
JOIN ref.source_publishing sp ON sp.source = s.source AND sp.publishable
GROUP BY s.source;