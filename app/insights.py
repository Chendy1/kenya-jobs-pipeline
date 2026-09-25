"""Insights tab: skills, counties, trends and lifetimes, with the statistics kept honest.

Rules applied everywhere: show the count next to every share, hide small samples, show
uncertainty, and switch analyses off until the data can support them."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st


import styling
from jobs_db import query_df

MIN_SKILL_N = 5
MIN_COUNTY_N = 10
MIN_TREND_DAYS = 28
MIN_WINDOW_N = 20
MIN_LIFETIME_EVENTS = 30


@st.cache_data(ttl=300, show_spinner=False)
def load(sql: str) -> pd.DataFrame:
    df = query_df(sql)
    for col in df.columns:  # NUMERIC arrives as Decimal: make it float so pandas and charts behave
        if df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = df[col].map(lambda v: float(v) if isinstance(v, Decimal) else v)
    return df


def render() -> None:
    cov = load("SELECT * FROM dw.v_coverage_overall").iloc[0]
    if pd.isna(cov["postings"]) or int(cov["postings"]) == 0:
        styling.empty_state("📊", "No data to analyse yet.")
        return
    history = 0 if pd.isna(cov["history_days"]) else int(cov["history_days"])
    src = load("SELECT * FROM dw.v_coverage_sources ORDER BY postings DESC")
    _coverage(cov, src, history)
    st.divider()
    _skills()
    st.divider()
    _counties()
    st.divider()
    _trends(history)
    st.divider()
    _lifetimes()
    _method()


def _coverage(cov, src, history: int) -> None:
    st.subheader("Read this first")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Postings analysed", f"{int(cov['postings']):,}")
    c2.metric("Sources", int(cov["sources"]))
    c3.metric("Days of history", history)
    c4.metric("First collected", str(cov["first_crawl"]))
    st.dataframe(pd.DataFrame({
        "Source": src["source"], "Postings": src["postings"], "Share (%)": src["share_pct"],
        "Data/software postings": src["tech_postings"], "With county (%)": src["pct_with_county"],
        "With salary band (%)": src["pct_with_salary"], "Days of history": src["history_days"],
    }), hide_index=True)
    top = src.iloc[0]
    if float(top["share_pct"]) >= 60:
        st.warning(f"Source mix: {top['source']} supplies {float(top['share_pct']):.0f}% of the postings, "
                   "so overall figures mostly describe that source.")
    if "jsearch" in set(src["source"]):
        st.warning("JSearch is queried mainly for data and software roles, so skill shares describe "
                   "tech postings on these sources, not the whole job market.")
    if history < MIN_TREND_DAYS:
        st.info(f"Only {history} day(s) of history: trends need {MIN_TREND_DAYS} days of daily collection "
                "and are switched off below.")
    st.caption("Every percentage is shown with the number of postings behind it. Small samples are hidden or flagged.")


def _skills() -> None:
    st.subheader("Most requested skills")
    sk = load("SELECT * FROM dw.v_skill_demand WHERE reliable")
    if sk.empty:
        st.info(f"No skill appears in at least {MIN_SKILL_N} data or software postings yet, so none is shown.")
        return
    n_tech = int(sk["n_tech"].iloc[0])
    balanced = st.toggle("Weight every source equally", value=False,
                         help="Pooled shares are dominated by whichever source has the most postings. "
                              "This averages each source's own share instead.")
    col = "balanced_pct" if balanced else "pooled_pct"
    top = sk.sort_values([col, "postings"], ascending=False).head(15)
    st.bar_chart(top, x="skill_name", y=col, horizontal=True, sort=False)
    st.dataframe(pd.DataFrame({
        "Skill": top["skill_name"],
        "Postings": top["postings"],
        "Share of data/software postings (%)": top["pooled_pct"],
        "95% interval (%)": [f"{lo:.1f} to {hi:.1f}" for lo, hi in zip(top["ci_low_pct"], top["ci_high_pct"])],
        "Weighted per source (%)": top["balanced_pct"],
        "Sources mentioning": [f"{int(a)} of {int(b)}" for a, b in zip(top["sources_mentioning"], top["sources_total"])],
    }), hide_index=True)
    st.caption(f"Denominator: {n_tech} postings in the Data & Analytics and Software & IT categories, from "
               f"sources with at least 10 such postings. Only skills in at least {MIN_SKILL_N} postings are shown. "
               "The interval is the sampling uncertainty: with few postings it is wide.")


def _counties() -> None:
    st.subheader("Where the postings are")
    cs = load("SELECT * FROM dw.v_county_summary ORDER BY postings DESC")
    if cs.empty:
        st.info("No postings with a stated county yet.")
        return
    solid = cs[cs["reliable"]]
    rest = cs[~cs["reliable"]]
    n_located = int(cs["n_located"].iloc[0])
    if solid.empty:
        st.info(f"No county has {MIN_COUNTY_N} or more postings yet, so counties are not compared.")
    else:
        st.bar_chart(solid.head(15), x="county_name", y="share_pct", horizontal=True, sort=False)
        st.dataframe(pd.DataFrame({
            "County": solid["county_name"],
            "Postings": solid["postings"],
            "Share of county-located postings (%)": solid["share_pct"],
            "95% interval (%)": [f"{lo:.1f} to {hi:.1f}" for lo, hi in zip(solid["ci_low_pct"], solid["ci_high_pct"])],
            "Sources": solid["sources"],
            "With salary band": solid["n_salary"],
            "Median advertised band midpoint (KES/month)": solid["median_salary_band_mid_kes"],
        }), hide_index=True)
    if not rest.empty:
        st.caption(f"{len(rest)} counties have fewer than {MIN_COUNTY_N} postings each "
                   f"({int(rest['postings'].sum())} postings in total) and are not compared.")
    st.caption(f"Based on {n_located} postings that name a county; postings that say only 'Kenya' are excluded. "
               "Salary medians appear only for counties with at least 5 postings that state a band, and are "
               "medians of band midpoints, not pay.")


def _trends(history: int) -> None:
    st.subheader("Hiring trends")
    if history < MIN_TREND_DAYS:
        st.progress(min(history / MIN_TREND_DAYS, 1.0), text=f"{history} of {MIN_TREND_DAYS} days collected")
        st.caption("Trends count only postings posted after collection began. Counting jobs that were already "
                   "open on day one would favour long-lived postings and fake a rising trend. "
                   "They switch on automatically once enough history exists.")
        return
    w = load("SELECT week_start, county_name, location_type, sum(postings)::int AS postings "
             "FROM dw.v_weekly_new_postings WHERE week_complete GROUP BY 1, 2, 3 ORDER BY 1")
    if w.empty or w["week_start"].nunique() < 3:
        st.info("Fewer than 3 complete weeks so far: not enough to show a trend.")
        return
    total = w.groupby("week_start")["postings"].sum()
    counties = w[w["location_type"] == "county"]
    top = counties.groupby("county_name")["postings"].sum().nlargest(5).index
    pivot = counties[counties["county_name"].isin(top)].pivot_table(
        index="week_start", columns="county_name", values="postings", aggfunc="sum", fill_value=0)
    pivot["All postings"] = total
    pivot = pivot.fillna(0)
    pivot.index = pd.to_datetime(pivot.index)
    st.line_chart(pivot)
    st.caption("New postings per week, by the date they were posted. Only complete weeks are shown. "
               "Feed depth and source mix can move these numbers, so treat small changes as noise.")


def _lifetimes() -> None:
    st.subheader("How long postings stay open")
    st.markdown("**1. Advertised window** (closing date minus posted date): needs no censoring correction.")
    aw = load("SELECT * FROM dw.v_advertised_window_stats ORDER BY (source = 'all') DESC, postings DESC")
    enough = [n >= MIN_WINDOW_N for n in aw["with_window"]]
    st.dataframe(pd.DataFrame({
        "Source": aw["source"],
        "Postings": aw["postings"],
        "With a closing date": aw["with_window"],
        "Share with a closing date (%)": aw["pct_with_window"],
        "Median days advertised": [v if ok else None for v, ok in zip(aw["median_days"], enough)],
        "Middle half (days)": [f"{a:.0f} to {b:.0f}" if ok and pd.notna(a) else "" for a, b, ok
                               in zip(aw["p25_days"], aw["p75_days"], enough)],
    }), hide_index=True)
    st.caption(f"Statistics appear only where at least {MIN_WINDOW_N} postings state a closing date. "
               "Postings without one are not included, and may differ from those that state one.")

    st.markdown("**2. Observed time in the listings** (right-censored).")
    ls = load("SELECT * FROM dw.v_lifetime_summary ORDER BY source")
    if ls.empty:
        st.info("No postings first seen after collection began yet, so observed lifetimes cannot be measured.")
        return
    st.dataframe(pd.DataFrame({
        "Source": ls["source"],
        "Postings watched": ls["cohort_postings"],
        "Left the listing": ls["left_listing"],
        "Still visible (censored)": ls["still_visible"],
        "Median days (Kaplan-Meier)": ls["median_days"],
        "Days of postings one crawl covers": ls["feed_window_days"],
        "Trustworthy": ls["trustworthy"].fillna(False).astype(bool),
    }), hide_index=True)
    trusted = ls.loc[ls["trustworthy"].fillna(False).astype(bool), "source"].tolist()
    if trusted:
        km = load("SELECT source, age_days, survival FROM dw.v_lifetime_km")
        km = km[km["source"].isin(trusted)]
        st.line_chart(km.pivot_table(index="age_days", columns="source", values="survival"))
        st.caption("Share of postings still visible after N days. Postings still open are treated as "
                   "unfinished, not as short-lived.")
    else:
        st.warning("Not shown: with the crawl as it stands, a posting leaves our view because newer postings push "
                   "it off the pages we read, not because it closed. A lifetime is reported only when at least "
                   f"{MIN_LIFETIME_EVENTS} postings have left the listing and the estimated median is well above "
                   "the days of postings one crawl covers. Reading deeper listing pages, or re-checking known "
                   "postings, would make this measurable.")


def _method() -> None:
    with st.expander("Method and limits"):
        st.markdown(f"""
- **Intervals:** Wilson 95% score intervals for proportions; they narrow as the number of postings grows.
- **Minimum samples:** skills in at least {MIN_SKILL_N} postings, counties with at least {MIN_COUNTY_N},
  trends after {MIN_TREND_DAYS} days of history, lifetime medians only with at least {MIN_LIFETIME_EVENTS}
  postings that left the listing.
- **Skills** come from a keyword dictionary; categories and seniority from keyword rules. Both are approximate.
- **Source mix:** sources differ in coverage and in what they are queried for. The equal-weight toggle shows how
  much the picture depends on that.
- **Duplicates** across sources are counted once. Postings that state no salary or county are left out of those
  particular statistics, and may not be typical.
- **Salaries** are the bands employers advertise, not pay.
""")