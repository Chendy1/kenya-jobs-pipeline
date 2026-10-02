"""Compliance as code: which sources we may use, and on what basis.

registry.build() calls require_allowed() for every source. Re-read a source's robots.txt and
terms before changing its entry, and update `checked`. Engineering documentation, not legal advice.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class SourceNotAllowed(RuntimeError):
    pass


@dataclass(frozen=True)
class Policy:
    status: str   # "open" | "consent_required" | "unsupported"
    basis: str
    terms_url: str
    checked: str  # date the terms were last read


POLICY: dict[str, Policy] = {
    "remotive": Policy(
        "open",
        "official free public API (remotive.com/api-documentation); no key needed; terms require "
        "linking back and crediting Remotive, and calling it only a few times a day",
        "https://github.com/remotive-com/remote-jobs-api", "2026-09-25"),
    "myjobmag": Policy(
        "open",
        "robots.txt allows /job/ and listing pages (it disallows search and any URL with a query "
        "string); the terms (revised 2012) have no automated-access clause",
        "https://www.myjobmag.co.ke/terms", "2026-09-24"),
    "reliefweb": Policy(
        "open",
        "official API; pre-approved appname required; 1,000 calls/day; content belongs to its "
        "publishers, so link back and do not republish",
        "https://apidoc.reliefweb.int/", "2026-09-24"),
    "jsearch": Policy(
        "open",
        "licensed API, free tier of 200 requests/month (hard limit); do not republish descriptions",
        "https://www.openwebninja.com/terms", "2026-09-24"),
    "jooble": Policy(
        "open", "official API, free key issued on request",
        "https://jooble.org/api/about", "2026-09-24"),
    "brightermonday": Policy(
        "consent_required",
        "terms bar robots and screen scraping for reproducing site content without prior written "
        "consent, and limit site information to personal non-commercial use",
        "https://www.brightermonday.co.ke/terms", "2026-09-24"),
    "fuzu": Policy(
        "consent_required",
        "service terms (v2, June 2026) prohibit scraping or extracting platform data without "
        "authorisation",
        "https://www.fuzu.com/legal/terms", "2026-09-24"),
    "adzuna": Policy(
        "unsupported",
        "the Adzuna API has no Kenya market (its only African market is South Africa)",
        "https://developer.adzuna.com/overview", "2026-09-24"),
        "oyk": Policy(
        "open",
        "robots.txt (checked 2026-09-25) allows our User-Agent with Crawl-delay: 120s, no Disallow; "
        "NOTE: OYK is a self-described secondary aggregator that republishes from undisclosed "
        "sources, so individual postings' true origin cannot be verified — a posting here may be "
        "a rewritten copy of a source excluded elsewhere in this project (e.g. BrighterMonday)",
        "https://opportunitiesforyoungkenyans.co.ke/robots.txt", "2026-09-25"),
}


def require_allowed(source: str) -> Policy:
    policy = POLICY.get(source)
    if policy is None:
        raise SourceNotAllowed(
            f"'{source}' has no entry in POLICY. Read its robots.txt and terms, then add one.")
    if policy.status == "unsupported":
        raise SourceNotAllowed(f"'{source}' is not usable: {policy.basis}.")
    if policy.status == "consent_required":
        var = f"CONSENT_{source.upper()}"
        if not os.getenv(var):
            raise SourceNotAllowed(
                f"'{source}' needs written permission: {policy.basis}. Terms: {policy.terms_url}. "
                f"Once you have permission, set {var}=<date of the permission> in .env.")
    return policy