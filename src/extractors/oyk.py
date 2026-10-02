"""Opportunities for Young Kenyans (OYK): polite WordPress-site extractor.

robots.txt (checked 2026-09-25): our User-Agent is unrestricted but MUST wait
Crawl-delay: 120 seconds between requests. Enforced here explicitly (belt and braces,
regardless of what PoliteSession itself parses from robots.txt).

KNOWN LIMITATION: OYK republishes from undisclosed secondary sources. We cannot verify
whether a given posting originated from a source excluded elsewhere in this project.
See policy.py.

FIRST-PASS SCAFFOLD: written without seeing real page HTML. Tries JSON-LD first (WordPress
SEO plugins often emit it), falls back to a generic <h1>/main-content read. Expect to
iterate against real pages the same way myjobmag.py was corrected in Phase 7.
"""
from __future__ import annotations

import logging
import re
import time
import json
from datetime import datetime
from typing import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from src.extractors.base import Extractor, Fetched
from src.extractors.jsonld import build_record, extract_page_meta
from src.storage.raw_store import utcnow
from src.utils.http import PoliteSession, RobotsDisallowed

log = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 120  # robots.txt Crawl-delay, enforced regardless of PoliteSession's own handling




_POST_PATH = re.compile(r"^/\d{4}/\d{2}/\d{2}/[^/]+/?$")


def post_links(html: str, base: str) -> list[str]:
    """A real post permalink always has a /YYYY/MM/DD/slug/ date prefix on this site.
    Nav links, taxonomy pages, author archives, and static pages (About Us, Contact,
    Privacy Policy, etc.) never do -- this is a structural filter, not a slug blacklist,
    so it doesn't need updating every time the site adds a new static page."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base + "/", a["href"]))[0]
        p = urlparse(url)
        if p.netloc == host and not p.query and _POST_PATH.match(p.path) and url not in links:
            links.append(url)
    return links


    
_TITLE_COMPANY = [
    re.compile(r"^\d[\d,]*\s+(?:job\s+)?(?:vacanc(?:y|ies)|internship opportunit(?:y|ies)|opportunit(?:y|ies))"
               r"\s+open\s*(?:at)?\s*(?P<c>.+)$", re.I),               
    re.compile(r"^(?:internship\s+)?opportunit(?:y|ies)\s+open\s+at\s+(?P<c>.+)$", re.I),
    re.compile(r"^(?P<c>.+?)\s+announces\s+\d[\d,]*\s+job\s+vacanc(?:y|ies)\b", re.I),
    re.compile(r"^(?P<c>.+?)\s+(?:is\s+)?(?:hiring|recruiting)\b", re.I),
]


def company_from_title(title: str) -> str | None:
    """OYK puts the employer in the headline: '103 Vacancies Open At Java House',
    'X Announces 6 Job Vacancies', 'X Hiring Y'."""
    t = re.sub(r"\s+", " ", title or "").strip()
    t = re.sub(r"\s+[–—-]\s+[A-Z][a-z]+\s+\d{4}$", "", t)  # drop a trailing "– September 2026"
    for pattern in _TITLE_COMPANY:
        m = pattern.match(t)
        if m:
            return m["c"].strip(" -–—:,") or None
    return None


def _vacancy_count(title: str) -> int | None:
    m = re.match(r"^(\d[\d,]*)\s", title) or re.search(r"announces\s+(\d[\d,]*)\s", title, re.I)
    return int(m[1].replace(",", "")) if m else None


def _published(soup) -> str | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes:
            if isinstance(node, dict) and node.get("datePublished"):
                return str(node["datePublished"])
    return None


def _details(text: str) -> dict:
    out: dict = {}
    m = re.search(r"Location:\s*(.+?)\s+(?:Employment Type|Career Level|Application Deadline):", text)
    if m:
        out["location"] = m[1].strip()
    m = re.search(r"Employment Type:\s*(.+?)\s+(?:Career Level|Application Deadline|Location):", text)
    if m:
        out["employment_type"] = m[1].strip()
    m = re.search(r"Application Deadline:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        try:
            out["deadline"] = datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%d %B %Y").date().isoformat()
        except ValueError:
            pass
    return out


def parse_post(source: str, url: str, html: str, fetched_at: str) -> dict | None:
    record = build_record(source, url, html, fetched_at)  # a real JobPosting JSON-LD, if one ever appears
    if record is not None:
        return record

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        return None
    published = _published(soup)  # read before the scripts are stripped below

    main = (soup.find("article") or soup.find(class_=re.compile(r"entry-content|post-content"))
            or soup.body)
    for tag in (main or soup)(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    body = (main or soup).get_text(" ", strip=True) if main else ""

    d = _details(body)
    company = company_from_title(title)
    count = _vacancy_count(title)
    posting = {
        "title": title,
        "hiringOrganization": {"name": company} if company else None,
        "jobLocation": {"address": {"addressLocality": d["location"]}} if d.get("location") else None,
        "datePosted": published,
        "validThrough": d.get("deadline"),
        "employmentType": d.get("employment_type"),
        "description": body[:8000] or None,
    }
    return {
        "source": source, "url": url, "fetched_at": fetched_at,
        "job_posting": {k: v for k, v in posting.items() if v},
        "page_meta": extract_page_meta(html),
        "vacancy_count": count,
        # a roundup announces several jobs in one article: one row is NOT one job
        "is_roundup": bool((count or 1) > 1 or body.count("Location:") > 1),
        "parsed_from": "html_article",
    }

class OYKExtractor(Extractor):
    source = "oyk"
    BASE = "https://opportunitiesforyoungkenyans.co.ke"

    def __init__(self, listing_url: str | None = None, pages: int = 1):
        self.listing_url = listing_url or self.BASE + "/"
        self.pages = max(1, pages)
        self.http = PoliteSession()
        self._last_request = 0.0

    def _throttled_get(self, url: str):
        gap = time.monotonic() - self._last_request
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        self._last_request = time.monotonic()
        return self.http.get(url)

    def _listing_pages(self) -> Iterator[str]:
        yield self.listing_url
        for n in range(2, self.pages + 1):
            yield f"{self.listing_url.rstrip('/')}/page/{n}/"

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        self.seen = set()
        handled: set[str] = set()
        fetched = 0
        for page_url in self._listing_pages():
            if fetched >= max_items:
                break
            try:
                listing = self._throttled_get(page_url)
            except RobotsDisallowed:
                log.warning("robots.txt disallows %s", page_url)
                continue
            for url in post_links(listing.text, self.BASE):
                self.seen.add(url)
                if fetched >= max_items or url in handled or already_done(url):
                    continue
                handled.add(url)
                try:
                    resp = self._throttled_get(url)
                except RobotsDisallowed:
                    log.warning("robots.txt disallows %s", url)
                    continue
                except Exception as exc:
                    log.warning("failed %s: %s", url, exc)
                    continue
                record = parse_post(self.source, url, resp.text, utcnow().isoformat())
                if record is None:
                    log.warning("no post content found on %s", url)
                    continue
                fetched += 1
                yield Fetched(record=record, snapshot=resp.text, snapshot_id=url)