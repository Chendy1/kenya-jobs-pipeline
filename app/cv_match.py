"""Match an uploaded CV against current postings by skill overlap.

Privacy: the CV is processed in memory for this session only. It is never written to
disk, the database, or any log. Closing the tab discards it.

Method: the SAME keyword skill-dictionary used to tag job postings (src/transform/skills)
is run against your CV text, then postings are ranked by how many of those skills they
also mention. This is plain keyword overlap, not a trained recommender — treat the
ranking as a starting point for browsing, not a verdict.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import styling
from jobs_db import query_df

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from src.transform.skills import extract_skills  # pure logic, no DB/network deps


def _extract_text(uploaded_file) -> str:
    if uploaded_file.type == "application/pdf":
        if pdfplumber is None:
            st.error("PDF support isn't installed. Run: pip install pdfplumber")
            return ""
        with pdfplumber.open(uploaded_file) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return uploaded_file.read().decode("utf-8", errors="ignore")


@st.cache_data(ttl=300, show_spinner=False)
def _all_jobs() -> pd.DataFrame:
    return query_df("SELECT job_posting_key, title, company_name, county_name, url, "
                    "date_posted, category, seniority, skills FROM dw.v_public_jobs "
                    "ORDER BY date_posted DESC NULLS LAST")


def render() -> None:
    st.subheader("Match your CV to current postings")
    st.caption("Your CV is processed only in this browser session — it is never saved, "
              "logged, or sent anywhere beyond this page. Refreshing discards it.")

    uploaded = st.file_uploader("Upload your CV (PDF or plain text)", type=["pdf", "txt"])
    pasted = st.text_area("...or paste your CV text here instead", height=150) if not uploaded else ""

    text = _extract_text(uploaded) if uploaded else pasted
    if not text.strip():
        styling.empty_state("📄", "Upload a CV or paste its text to see matching postings.")
        return

    my_skills = sorted({name for name, _category in extract_skills(text)})
    if not my_skills:
        st.warning("No skills from our dictionary were found in this text. The matcher only "
                  "recognises the same fixed skill list used to tag job postings — see the "
                  "About tab for the full list. Try pasting the skills/experience section directly.")
        return

    st.write("**Skills detected in your CV:**")
    st.markdown(" ".join(styling.status_pill(s, "green") for s in my_skills), unsafe_allow_html=True)

    jobs = _all_jobs()
    jobs = jobs[jobs["skills"].map(bool)].copy()
    if jobs.empty:
        st.info("No postings with tagged skills to compare against yet.")
        return

    my_set = set(my_skills)
    jobs["matched"] = jobs["skills"].map(lambda s: sorted(my_set & set(s)))
    jobs["match_count"] = jobs["matched"].map(len)
    jobs["missing"] = jobs["skills"].map(lambda s: sorted(set(s) - my_set))
    ranked = jobs[jobs["match_count"] > 0].sort_values(
        ["match_count", "date_posted"], ascending=[False, False])

    if ranked.empty:
        st.info("No current postings share any of your detected skills. Try browsing the "
               "Jobs tab directly, or check back as new postings come in.")
        return

    st.write(f"**{len(ranked)} postings share at least one skill with your CV**, best matches first:")
    for _, row in ranked.head(25).iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{row['title']}** — {row['company_name'] or 'Unknown company'}  \n"
                       f"{row['county_name'] or ''} · {row['category']} · {row['seniority']}")
            c2.metric("Skills matched", f"{row['match_count']}/{len(row['skills'])}")
            st.markdown(" ".join(styling.status_pill(s, "green") for s in row["matched"]) +
                       " " + " ".join(styling.status_pill(s, "grey") for s in row["missing"][:6]),
                       unsafe_allow_html=True)
            st.markdown(f"[Open posting]({row['url']})")

    st.caption("Green = a skill your CV and the posting share. Grey = a skill the posting "
              "wants that wasn't detected in your CV. Ranking is by count of shared skills "
              "only — it doesn't weigh seniority, salary, or location fit.")