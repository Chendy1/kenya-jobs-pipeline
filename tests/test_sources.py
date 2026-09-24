import pytest

from src.extractors.myjobmag import job_links, parse_job_page
from src.extractors.policy import SourceNotAllowed, require_allowed
from src.transform.adapters import jooble_adapter, jsearch_adapter, jsonld_adapter, reliefweb_adapter
from src.transform.cleaners import parse_salary_text
from src.transform.counties import map_location

JOB_HTML = """
<html><head><title>HR Assistant at Generations Techzone | MyJobMag</title>
<meta property="og:title" content="HR Assistant at Generations Techzone | MyJobMag"></head><body>
<a href="/jobs-by-field">Jobs by Field</a><a href="/jobs-by-type/remote">Remote Jobs</a>
<h1>HR Assistant at Generations Techzone</h1>
<a href="https://www.myjobmag.co.ke/jobs-at/generations-techzone">View Jobs at Generations Techzone</a>
<div><span>Posted:</span> <span>Sep 22, 2026</span></div>
<div><span>Deadline:</span> <span>Not specified</span></div>
<ul>
<li><span>Job Type</span><span><a href="/jobs-by-type/full-time">Full Time</a></span></li>
<li><span>Qualification</span><span><a href="/jobs-by-education/bsc">BA/BSc/HND</a></span></li>
<li><span>Experience</span><span>2 years</span></li>
<li><span>Location</span><span><a href="/jobs-location/nairobi">Nairobi</a></span></li>
<li><span>Job Field</span><span><a href="/jobs-by-field/human-resources">Human Resources / HR</a></span></li>
<li><span>Salary Range</span><span>KSh 30,000 - KSh 50,000/month</span></li>
</ul>
<ul><li>Recruitment and onboarding</li><li>Payroll and statutory compliance support</li></ul>
<h2>Method of Application</h2><p>Apply using the button.</p>
</body></html>
"""


def test_policy_gates(monkeypatch):
    monkeypatch.delenv("CONSENT_BRIGHTERMONDAY", raising=False)
    monkeypatch.delenv("CONSENT_FUZU", raising=False)
    require_allowed("myjobmag")
    for source in ("brightermonday", "fuzu", "adzuna", "unknown-site"):
        with pytest.raises(SourceNotAllowed):
            require_allowed(source)
    monkeypatch.setenv("CONSENT_BRIGHTERMONDAY", "2026-10-01")
    require_allowed("brightermonday")


def test_job_links_only_single_job_pages():
    html = ('<a href="/job/a-b">x</a><a href="/job/a-b/save">save</a>'
            '<a href="/job-application/1">apply</a><a href="/jobs/company-page">c</a>'
            '<a href="/job/c?utm=1">q</a><a href="https://other.com/job/z">o</a>'
            '<a href="https://www.myjobmag.co.ke/job/d-e#frag">d</a><a href="/job/a-b">dup</a>')
    assert job_links(html, "https://www.myjobmag.co.ke") == [
        "https://www.myjobmag.co.ke/job/a-b", "https://www.myjobmag.co.ke/job/d-e"]


def test_myjobmag_page_flows_through_the_adapter():
    rec = parse_job_page("myjobmag", "https://www.myjobmag.co.ke/job/hr-assistant-generations-techzone",
                         JOB_HTML, "2026-09-24T00:00:00+00:00")
    jp = rec["job_posting"]
    assert jp["title"] == "HR Assistant"
    assert jp["hiringOrganization"]["name"] == "Generations Techzone"
    assert jp["datePosted"] == "2026-09-22" and "validThrough" not in jp
    assert "Payroll" in jp["description"]
    a = jsonld_adapter(rec)
    assert a["company"] == "Generations Techzone"
    assert map_location(a["location_text"])["county"] == "Nairobi"
    s = parse_salary_text(a["salary_text"])
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (30000, 50000)


def test_reliefweb_adapter():
    payload = {"url": "https://reliefweb.int/job/1/x", "job": {
        "title": "Data Officer", "source": [{"name": "UNICEF"}], "city": [{"name": "Nairobi"}],
        "country": [{"name": "Kenya"}], "type": [{"name": "Job"}], "body-html": "<p>Python and SQL</p>",
        "date": {"created": "2026-09-20T10:00:00+00:00", "closing": "2026-10-05T00:00:00+00:00"}}}
    a = reliefweb_adapter(payload)
    assert a["company"] == "UNICEF" and a["location_text"] == "Nairobi"
    assert a["valid_through"].startswith("2026-10-05")


def test_jsearch_adapter_never_guesses_a_currency():
    job = {"job_title": "Data Engineer", "employer_name": "Acme", "job_location": "Nairobi, Kenya",
           "job_min_salary": 60000, "job_max_salary": 90000, "job_salary_period": "MONTH",
           "job_posted_at_datetime_utc": "2026-09-14T00:00:00.000Z",
           "required_technologies": ["Python", "SQL"], "job_apply_link": "https://example.com/apply"}
    a = jsearch_adapter({"job_id": "abc", "job": job})
    assert a["base_salary"] is None and a["skills_text"] == "Python, SQL"
    job["job_salary_string"] = "KSh 60K-90K a month"
    assert jsearch_adapter({"job_id": "abc", "job": job})["base_salary"]["currency"] == "KES"


def test_jooble_adapter_salary_text():
    a = jooble_adapter({"job": {"title": "Analyst", "company": "X", "location": "Nairobi",
                                "salary": "Ksh 50k - 70k monthly", "link": "https://jooble.org/desc/1"}})
    s = parse_salary_text(a["salary_text"])
    assert (s["min_monthly_kes"], s["max_monthly_kes"]) == (50000, 70000)


def test_jsearch_respects_request_cap_and_drops_relative_time(monkeypatch):
    from src.extractors.jsearch import JSearchExtractor

    monkeypatch.setenv("JSEARCH_API_KEY", "test")
    ex = JSearchExtractor(queries=["q1", "q2"], max_requests=2)
    pages = [{"data": {"jobs": [{"job_id": "1", "job_title": "A", "job_posted_at": "2 days ago"}],
                       "cursor": "c1"}},
             {"data": {"jobs": [{"job_id": "2", "job_title": "B"}]}}]
    calls = []

    class FakeApi:
        def request(self, method, url, **kw):
            calls.append(kw.get("params", {}))
            return pages[len(calls) - 1]

    ex.api = FakeApi()
    items = list(ex.fetch(10, lambda _id: False))
    assert len(calls) == 2 and len(items) == 2
    assert "job_posted_at" not in items[0].record["job"]

def test_jsearch_same_job_with_different_ids_gets_one_identity():
    from src.extractors.jsearch import fingerprint

    a = {"job_id": "AAA", "employer_name": "Acme Ltd", "job_title": "Data Engineer",
         "job_location": "Nairobi, Kenya"}
    b = {"job_id": "BBB", "employer_name": "ACME LTD ", "job_title": "data engineer",
         "job_location": "Nairobi, Kenya"}
    assert fingerprint(a) == fingerprint(b)


def test_observed_fields_never_change_the_content_hash():
    from src.storage.raw_store import content_hash

    base = {"job_id": "k", "job": {"job_title": "x"}}
    assert content_hash({**base, "observed": {"job_id": "AAA"}}) == \
        content_hash({**base, "observed": {"job_id": "BBB"}})