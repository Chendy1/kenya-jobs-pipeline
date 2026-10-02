"""Kenya jobs explorer.

    python -m streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


import insights
import cv_match
import styling
from jobs_db import mode, query_df

st.set_page_config(page_title="Kenya Jobs Explorer", layout="wide", page_icon="🇰🇪")
styling.inject()

PRIVATE = mode() == "private"
JOBS = "dw.v_jobs_enriched" if PRIVATE else "dw.v_public_jobs"
LIMIT = 500


# ---------------------------------------------------------------- data access
@st.cache_data(ttl=300, show_spinner=False)
def filter_options() -> dict:
    def first_col(sql: str) -> list:
        return query_df(sql).iloc[:, 0].tolist()

    return {
        "counties": first_col(f"SELECT county_name FROM {JOBS} WHERE location_type = 'county' "
                              "GROUP BY 1 ORDER BY count(*) DESC, 1"),
        "categories": first_col(f"SELECT category FROM {JOBS} GROUP BY 1 ORDER BY count(*) DESC, 1"),
        "seniorities": first_col(f"SELECT seniority FROM {JOBS} GROUP BY 1 ORDER BY count(*) DESC, 1"),
        "sources": first_col(f"SELECT source FROM {JOBS} GROUP BY 1 ORDER BY 1"),
        "skills": first_col(f"SELECT skill FROM (SELECT unnest(skills) AS skill FROM {JOBS}) t "
                            "GROUP BY 1 ORDER BY count(*) DESC, 1"),
    }


@st.cache_data(ttl=300, show_spinner="Searching...")
def search(text, counties, categories, seniorities, sources, skills, skills_mode,
           days, salary_only, remote_only) -> pd.DataFrame:
    clauses, params = ["TRUE"], []
    if text:
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(title ILIKE %s OR company_name ILIKE %s)")
        params += [like, like]
    if counties:
        clauses.append("county_name = ANY(%s)")
        params.append(list(counties))
    if categories:
        clauses.append("category = ANY(%s)")
        params.append(list(categories))
    if seniorities:
        clauses.append("seniority = ANY(%s)")
        params.append(list(seniorities))
    if sources:
        clauses.append("source = ANY(%s)")
        params.append(list(sources))
    if skills:
        clauses.append("skills " + ("@>" if skills_mode == "all" else "&&") + " %s::text[]")
        params.append(list(skills))
    if days:
        clauses.append("date_posted >= (now() AT TIME ZONE 'Africa/Nairobi')::date - %s")
        params.append(int(days))
    if salary_only:
        clauses.append("has_salary")
    if remote_only:
        clauses.append("is_remote")
    sql = (f"SELECT *, count(*) OVER () AS total FROM {JOBS} WHERE {' AND '.join(clauses)} "
           f"ORDER BY date_posted DESC NULLS LAST, job_posting_key DESC LIMIT {LIMIT}")
    return query_df(sql, params)


def band(lo, hi) -> str:
    if pd.isna(lo) or pd.isna(hi):
        return ""
    return f"{int(lo):,} - {int(hi):,}"


def to_local(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert("Africa/Nairobi").dt.strftime("%Y-%m-%d %H:%M")
    return df


# ---------------------------------------------------------------- header

styling.header("Kenya Jobs Explorer",
               "Job listings collected from Kenyan boards and licensed APIs — search, filter, and follow the link back to the source.")
if PRIVATE:
    st.error("PRIVATE MODE: this view includes sources that are not cleared for publication. "
             "Use it only on your own machine. Never deploy it or share screenshots.")


tab_jobs, tab_overview, tab_insights, tab_cv, tab_health, tab_about = st.tabs(
    ["Jobs", "Overview", "Insights", "Match My CV", "Pipeline health", "About"])
# ---------------------------------------------------------------- jobs
with tab_jobs:
    opts = filter_options()
    text = st.text_input("Search title or company", placeholder="e.g. data analyst, Safaricom")
    c1, c2, c3 = st.columns(3)
    counties = c1.multiselect("County", opts["counties"])
    categories = c2.multiselect("Category", opts["categories"])
    seniorities = c3.multiselect("Seniority", opts["seniorities"])
    c4, c5, c6 = st.columns(3)
    skills = c4.multiselect("Skills", opts["skills"])
    skills_mode = c4.radio("Match", ["any", "all"], horizontal=True) if skills else "any"
    days = c5.selectbox("Posted within", [7, 14, 30, 90, 0], index=2,
                        format_func=lambda d: "any time" if d == 0 else f"last {d} days")
    sources = c6.multiselect("Source", opts["sources"])
    c7, c8 = st.columns(2)
    salary_only = c7.checkbox("Only postings with an advertised salary band")
    remote_only = c8.checkbox("Only remote postings")

    df = search(text, counties, categories, seniorities, sources, skills, skills_mode,
                days, salary_only, remote_only)
    
    if df.empty:
        styling.empty_state("🔍", "No postings match these filters. Try widening the county, category, or date range.")
    else:
        total = int(df["total"].iloc[0])
        st.write(f"**{total:,}** matching postings" + (f" (showing the newest {LIMIT})" if total > LIMIT else ""))
        show = pd.DataFrame({
            "Posted": df["date_posted"],
            "Title": df["title"],
            "Company": df["company_name"],
            "County": df["county_name"],
            "Category": df["category"],
            "Seniority": df["seniority"],
            "Advertised salary band (KES/month)": [band(a, b) for a, b in zip(df["salary_min_kes"], df["salary_max_kes"])],
            "Skills": df["skills"].apply(lambda s: ", ".join(s[:6]) if s else ""),
            "Source": df["source"],
            "Link": df["url"],
        })
        st.dataframe(show, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")})
        st.caption("Salary bands are as advertised by employers (job boards use fixed ranges), not exact pay.")
        if PRIVATE:
            st.download_button("Download these results (CSV, private mode only)",
                               show.to_csv(index=False).encode("utf-8"), "kenya_jobs_results.csv", "text/csv")

# ---------------------------------------------------------------- overview
with tab_overview:
    kpi = query_df(f"""
        SELECT count(*) AS postings,
               count(DISTINCT company_name) AS companies,
               count(DISTINCT county_name) FILTER (WHERE location_type = 'county') AS counties,
               round(100.0 * count(*) FILTER (WHERE has_salary) / NULLIF(count(*), 0), 0) AS pct_salary,
               max(date_posted) AS newest
        FROM {JOBS}""").iloc[0]
    if int(kpi["postings"]) == 0:
        st.info("No data to show yet.")
    else:
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Postings", f"{int(kpi['postings']):,}")
        k2.metric("Companies", f"{int(kpi['companies']):,}")
        k3.metric("Counties covered", int(kpi["counties"]))
        k4.metric("With a salary band", f"{float(kpi['pct_salary'] or 0):.0f}%")
        k5.metric("Newest posting", str(kpi["newest"]))

        left, right = st.columns(2)
        with left:
            st.subheader("Postings by county (top 15)")
            by_county = query_df(f"SELECT county_name AS county, count(*) AS postings FROM {JOBS} "
                                 "WHERE location_type = 'county' GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
            st.bar_chart(by_county, x="county", y="postings", horizontal=True, sort=False)
            unspecified = query_df(f"SELECT count(*) FROM {JOBS} WHERE location_type <> 'county'").iloc[0, 0]
            st.caption(f"{int(unspecified):,} postings have no specific county (unspecified, remote or outside Kenya).")
        with right:
            st.subheader("Postings by category")
            by_cat = query_df(f"SELECT category, count(*) AS postings FROM {JOBS} GROUP BY 1 ORDER BY 2 DESC")
            st.bar_chart(by_cat, x="category", y="postings", horizontal=True, sort=False)
            other = by_cat.loc[by_cat["category"] == "Other", "postings"].sum()
            st.caption(f"Categories are assigned by keyword rules; {100 * other / by_cat['postings'].sum():.0f}% "
                       "are unclassified (Other).")

        left, right = st.columns(2)
        with left:
            st.subheader("Most requested skills (top 15)")
            top = query_df(f"SELECT skill, count(*) AS postings FROM (SELECT unnest(skills) AS skill FROM {JOBS}) t "
                           "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 15")
            st.bar_chart(top, x="skill", y="postings", horizontal=True, sort=False)
        with right:
            st.subheader("Postings per day (last 30 days)")
            daily = query_df(f"SELECT date_posted, count(*) AS postings FROM {JOBS} "
                             "WHERE date_posted >= (now() AT TIME ZONE 'Africa/Nairobi')::date - 30 "
                             "GROUP BY 1 ORDER BY 1")
            daily["date_posted"] = pd.to_datetime(daily["date_posted"])
            st.line_chart(daily, x="date_posted", y="postings")
with tab_insights:
    insights.render()
with tab_cv:
    cv_match.render()
# ---------------------------------------------------------------- pipeline health
with tab_health:
    runs = query_df("SELECT * FROM ops.v_public_runs")
    if runs.empty:
        st.info("The pipeline has not run yet.")
    else:
        now = pd.Timestamp.now(tz="UTC")
        last = runs.iloc[0]
        hours = (now - pd.to_datetime(last["started_at"], utc=True)).total_seconds() / 3600
        good = runs[runs["status"] == "ok"]
        h1, h2, h3 = st.columns(3)
        h1.markdown("**Latest run**")
        h1.markdown(styling.pill_for_status(str(last["status"])), unsafe_allow_html=True)
        h2.metric("Latest run started", f"{hours:.1f} hours ago")
        h3.metric("Latest successful run",
                  f"{(now - pd.to_datetime(good.iloc[0]['started_at'], utc=True)).total_seconds() / 3600:.1f} hours ago"
                  if not good.empty else "none yet")

        st.subheader("Data-quality checks (latest result per check)")
        dq = to_local(query_df("SELECT * FROM ops.v_public_dq_summary ORDER BY layer"), ["last_checked"])
        st.dataframe(dq, hide_index=True)

        st.subheader("Source freshness")
        st.dataframe(query_df("SELECT * FROM ops.v_public_source_freshness ORDER BY source"), hide_index=True)

        st.subheader("Recent runs")
        st.dataframe(to_local(runs[["id", "started_at", "duration_s", "status"]].copy(), ["started_at"]),
                     hide_index=True)
        st.caption("Failed runs are shown on purpose: the pipeline stops rather than publish bad data.")

        if PRIVATE:
            st.subheader("Failing checks (private)")
            failing = query_df("SELECT check_name, severity, detail, run_at FROM ops.v_latest_dq "
                               "WHERE NOT passed ORDER BY severity, check_name")
            st.dataframe(to_local(failing, ["run_at"]), hide_index=True)
            latest = query_df("SELECT summary->'errors' AS errors, summary->'warnings' AS warnings "
                              "FROM ops.pipeline_runs ORDER BY id DESC LIMIT 1")
            if not latest.empty:
                st.json({"errors": latest["errors"].iloc[0], "warnings": latest["warnings"].iloc[0]})

# ---------------------------------------------------------------- about
with tab_about:
    st.markdown("""
### What this is
A portfolio data-engineering project: job postings for Kenya are collected on a schedule, cleaned,
modelled into a star schema in PostgreSQL, checked by automated data-quality tests, and served here.

### Sources
- **MyJobMag Kenya:** collected politely, following its `robots.txt`.
- **ReliefWeb (UN OCHA):** official API; humanitarian and NGO jobs.
- **JSearch and Jooble:** licensed job-search APIs.

Sources that have not given permission for their listings to be shown are excluded from this public view.

### What is shown, and what is not
Only titles, companies, places, advertised salary bands and links back to the original posting.
Descriptions are never republished: follow the link to read the full advertisement at its source.

### Method and limits
- Counties are mapped from the location text; postings that say only "Kenya" have no county.
- Categories come from keyword rules and are approximate.
- Salaries are the bands employers advertise, not actual pay, and few postings state one.
- The same job on several sources is shown once.
- Source owners who want their listings removed can contact the project owner and will be removed promptly.
""")