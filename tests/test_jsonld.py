import json

from src.extractors.jsonld import build_record, extract_job_posting
from src.transform.adapters import jsonld_adapter
from src.transform.counties import map_location

GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "JobPosting", "@id": "x/JobPosting/listing-1", "title": "TRAINEE DEALER",
         "hiringOrganization": {"@id": "x/Organization/agency-1"},
         "jobLocation": {"@id": "x/Place/location-1",
                         "address": {"addressRegion": "Kenya", "addressCountry": "KE"}},
         "datePosted": "2026-09-21T00:00:00.000000Z"},
        {"@type": "Organization", "@id": "x/Organization/agency-1", "name": "Cotes Du Rhone Limited"},
        {"@type": "Place", "@id": "x/Place/location-1", "address": {"@id": "x/PostalAddress/1"}},
    ],
}
HTML = (
    "<html><head><title>TRAINEE DEALER at Cotes Du Rhone Limited | BrighterMonday</title>"
    '<meta property="og:title" content="TRAINEE DEALER in Nairobi">'
    '<meta name="description" content="Apply online today.">'
    f'<script type="application/ld+json">{json.dumps(GRAPH)}</script></head><body></body></html>'
)


def test_org_reference_is_resolved():
    posting = extract_job_posting(HTML)
    assert posting["hiringOrganization"]["name"] == "Cotes Du Rhone Limited"


def test_company_and_county_reach_the_adapter():
    record = build_record("brightermonday", "https://example.com/listings/x", HTML, "2026-09-24T00:00:00+00:00")
    a = jsonld_adapter(record)
    assert a["company"] == "Cotes Du Rhone Limited"
    assert map_location(a["location_text"])["county"] == "Nairobi"


def test_kenya_only_stays_unmapped():
    html = HTML.replace("in Nairobi", "in Kenya")
    record = build_record("brightermonday", "https://example.com/listings/x", html, "2026-09-24T00:00:00+00:00")
    assert map_location(jsonld_adapter(record)["location_text"])["county"] is None