"""Per-source adapters: map each source's raw payload to one common shape.

Phase 6 adds one adapter per new source (MyJobMag, Fuzu, Adzuna...).
"""
from __future__ import annotations


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


def jsonld_adapter(payload: dict) -> dict:
    jp = payload.get("job_posting") or payload
    org = _first(jp.get("hiringOrganization"))
    company = org.get("name") if isinstance(org, dict) else org
    return {
        "url": payload.get("url") or jp.get("url"),
        "title": jp.get("title"),
        "company": str(company) if company else None,
        "location_text": _location_text(jp.get("jobLocation")),
        "remote_hint": str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE",
        "date_posted": jp.get("datePosted"),
        "valid_through": jp.get("validThrough"),
        "employment_type": _joined(jp.get("employmentType")),
        "industry": _joined(jp.get("industry") or jp.get("occupationalCategory")),
        "description_html": jp.get("description"),
        "skills_text": _joined(jp.get("skills")) or "",
        "base_salary": jp.get("baseSalary"),
    }


ADAPTERS: dict = {}  # source name -> adapter; anything not listed uses the JSON-LD adapter


def get_adapter(source: str):
    return ADAPTERS.get(source, jsonld_adapter)