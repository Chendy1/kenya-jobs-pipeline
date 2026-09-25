"""Per-source adapters: map each source's raw payload to one common shape."""
from __future__ import annotations

import re


def _first(x):
    """schema.org fields may be a dict or a list of dicts."""
    if isinstance(x, list):
        return x[0] if x else None
    return x


def _joined(x) -> str | None:
    if isinstance(x, list):
        return ", ".join(str(i) for i in x) or None
    return str(x) if x else None


def _location_text(job_location) -> str:
    parts: list[str] = []
    locs = job_location if isinstance(job_location, list) else [job_location]
    for loc in locs:
        if isinstance(loc, str):
            parts.append(loc)
        elif isinstance(loc, dict):
            addr = loc.get("address", loc)
            if isinstance(addr, str):
                parts.append(addr)
            elif isinstance(addr, dict):
                for k in ("streetAddress", "addressLocality", "addressRegion"):
                    if addr.get(k):
                        parts.append(str(addr[k]))
    return ", ".join(parts)


def _location_from_page(page_meta, title) -> str | None:
    """BrighterMonday's og:title is '<title> in <place>' ('... in Kenya' when unspecified)."""
    og = ((page_meta or {}).get("og_title") or "").strip()
    prefix = f"{title or ''} in "
    if title and og.lower().startswith(prefix.lower()):
        return og[len(prefix):].strip() or None
    return None


def _currency_from_text(text) -> str | None:
    t = (text or "").lower()
    if re.search(r"\b(kes|ksh|kshs)\b", t):
        return "KES"
    if re.search(r"\busd\b|us\$|\$", t):
        return "USD"
    return None


def _names(items) -> list[str]:
    return [x["name"] for x in (items or []) if isinstance(x, dict) and x.get("name")]


def jsonld_adapter(payload: dict) -> dict:
    """schema.org JobPosting payloads (BrighterMonday, MyJobMag)."""
    jp = payload.get("job_posting") or payload
    org = _first(jp.get("hiringOrganization"))
    company = org.get("name") if isinstance(org, dict) else org
    parts = [
        _location_from_page(payload.get("page_meta"), jp.get("title")),
        _location_text(jp.get("jobLocation")),
    ]
    return {
        "url": payload.get("url") or jp.get("url"),
        "title": jp.get("title"),
        "company": str(company) if company else None,
        "location_text": ", ".join(dict.fromkeys(p for p in parts if p)),
        "remote_hint": str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE",
        "date_posted": jp.get("datePosted"),
        "valid_through": jp.get("validThrough"),
        "employment_type": _joined(jp.get("employmentType")),
        "industry": _joined(jp.get("industry") or jp.get("occupationalCategory")),
        "description_html": jp.get("description"),
        "skills_text": _joined(jp.get("skills")) or "",
        "base_salary": jp.get("baseSalary"),
        "salary_text": jp.get("salaryText"),
    }


def reliefweb_adapter(payload: dict) -> dict:
    f = payload.get("job") or {}
    orgs, cities, countries = _names(f.get("source")), _names(f.get("city")), _names(f.get("country"))
    date = f.get("date") or {}
    return {
        "url": payload.get("url") or f.get("url"),
        "title": f.get("title"),
        "company": orgs[0] if orgs else None,
        "location_text": ", ".join(cities or countries),
        "remote_hint": False,
        "date_posted": date.get("created"),
        "valid_through": date.get("closing"),
        "employment_type": ", ".join(_names(f.get("type"))) or None,
        "industry": ", ".join(_names(f.get("career_categories"))) or None,
        "description_html": f.get("body-html"),
        "skills_text": "",
        "base_salary": None,
        "salary_text": None,
    }

def jsearch_adapter(payload: dict) -> dict:
    j = {**(payload.get("observed") or {}), **(payload.get("job") or {})}

    currency = j.get("job_salary_currency") or _currency_from_text(j.get("job_salary_string"))
    base = None
    # no currency, no salary: assuming KES for a USD figure would corrupt the analytics
    if currency and (j.get("job_min_salary") or j.get("job_max_salary")):
        base = {"currency": currency,
                "value": {"minValue": j.get("job_min_salary"), "maxValue": j.get("job_max_salary"),
                          "unitText": str(j.get("job_salary_period") or "").upper()}}
    location = j.get("job_location") or ", ".join(p for p in (j.get("job_city"), j.get("job_country")) if p)
    return {
        "url": j.get("job_apply_link") or j.get("job_google_link"),
        "title": j.get("job_title"),
        "company": j.get("employer_name"),
        "location_text": location,
        "remote_hint": bool(j.get("job_is_remote")),
        "date_posted": j.get("job_posted_at_datetime_utc"),
        "valid_through": j.get("job_offer_expiration_datetime_utc"),
        "employment_type": j.get("job_employment_type"),
        "industry": j.get("industry") or j.get("job_function"),
        "description_html": j.get("job_description"),
        "skills_text": _joined(j.get("required_technologies")) or "",
        "base_salary": base,
        "salary_text": None,
    }


def jooble_adapter(payload: dict) -> dict:
    j = payload.get("job") or {}
    return {
        "url": j.get("link"),
        "title": j.get("title"),
        "company": j.get("company"),
        "location_text": j.get("location"),
        "remote_hint": False,
        "date_posted": j.get("updated"),  # "last updated", the closest thing Jooble gives
        "valid_through": None,
        "employment_type": j.get("type"),
        "industry": None,
        "description_html": j.get("snippet"),
        "skills_text": "",
        "base_salary": None,
        "salary_text": j.get("salary"),
    }

def remotive_adapter(payload: dict) -> dict:
    j = payload.get("job") or {}
    return {
        "url": j.get("url"),
        "title": j.get("title"),
        "company": j.get("company_name"),
        "location_text": j.get("candidate_required_location"),
        "remote_hint": True,  # Remotive lists remote jobs exclusively
        "date_posted": j.get("publication_date"),
        "valid_through": None,
        "employment_type": j.get("job_type"),
        "industry": j.get("category"),
        "description_html": j.get("description"),
        "skills_text": ", ".join(j.get("tags") or []),
        "base_salary": None,
        "salary_text": j.get("salary"),
    }


ADAPTERS: dict = {
    "reliefweb": reliefweb_adapter,
    "jsearch": jsearch_adapter,
    "jooble": jooble_adapter,
    "remotive": remotive_adapter,
}  # anything not listed (brightermonday, myjobmag) uses the JSON-LD adapter


def get_adapter(source: str):
    return ADAPTERS.get(source, jsonld_adapter)