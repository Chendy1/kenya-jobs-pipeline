"""MyJobMag Kenya: polite HTML extractor.

robots.txt (read 2026-09-24) disallows search and any URL containing '?', so we only follow
plain /job/<slug> links from the homepage feed (/, /page/2, ...) or a listing URL you give us.
If the site ever answers 403 or a CAPTCHA, stop. Do not work around it; ask for their XML feed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from src.extractors.base import Extractor, Fetched
from src.extractors.jsonld import build_record, extract_page_meta
from src.storage.raw_store import utcnow
from src.utils.http import PoliteSession, RobotsDisallowed

log = logging.getLogger(__name__)

_LABELS = ("Job Type", "Qualification", "Experience", "Location", "Job Field", "Salary Range")


def job_links(html: str, base: str) -> list[str]:
    """Only plain single-job pages: /job/<slug>. No queries, no /save, no /job-application."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base + "/", a["href"]))[0]
        p = urlparse(url)
        if p.netloc == host and not p.query and re.fullmatch(r"/job/[^/]+", p.path) and url not in links:
            links.append(url)
    return links


def _labelled(lines: list[str], label: str) -> str | None:
    """Value of a 'Label  value' pair, whether they are on one line or two."""
    for i, ln in enumerate(lines):
        if ln == label:
            return lines[i + 1] if i + 1 < len(lines) else None
        if ln.startswith(label + " "):
            return ln[len(label) + 1:].strip() or None
    return None


def _link_texts(soup: BeautifulSoup, prefix: str) -> list[str]:
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        if re.fullmatch(prefix + r"/[^/]+", urlparse(a["href"]).path):
            text = a.get_text(" ", strip=True)
            if text and text not in out:
                out.append(text)
    return out


def _iso_day(text: str | None) -> str | None:
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m[1][:3].title()} {m[2]} {m[3]}", "%b %d %Y").date().isoformat()
    except ValueError:
        return None


def parse_job_page(source: str, url: str, html: str, fetched_at: str) -> dict | None:
    record = build_record(source, url, html, fetched_at)  # JSON-LD, if the page has it
    if record is not None:
        return record

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        return None

    company = None
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if "/jobs-at/" in a["href"] and text.lower().startswith("view jobs at"):
            company = re.sub(r"^view jobs at\s+", "", text, flags=re.I).strip() or None
            break
    if company and title.endswith(f" at {company}"):
        title = title[: -len(f" at {company}")].strip()

    locations = _link_texts(soup, "/jobs-location")[:3]
    fields = _link_texts(soup, "/jobs-by-field")[:3]

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n", strip=True).splitlines() if ln.strip()]

    # description = the text after the last attribute row, up to "Method of Application"
    end = next((i for i, ln in enumerate(lines) if "method of application" in ln.lower()), len(lines))
    start = max((i for i, ln in enumerate(lines[:end]) if ln in _LABELS), default=-2)
    body = [ln for ln in lines[start + 2:end] if not ln.lower().startswith("check how your cv")]

    posting = {
        "title": title,
        "hiringOrganization": {"name": company} if company else None,
        "jobLocation": {"address": {"addressLocality": ", ".join(locations)}} if locations else None,
        "datePosted": _iso_day(_labelled(lines, "Posted:")),
        "validThrough": _iso_day(_labelled(lines, "Deadline:")),
        "employmentType": _labelled(lines, "Job Type"),
        "industry": ", ".join(fields) or None,
        "description": "\n".join(body) or None,
        "salaryText": _labelled(lines, "Salary Range"),
        "qualification": _labelled(lines, "Qualification"),
        "experience": _labelled(lines, "Experience"),
    }
    return {
        "source": source,
        "url": url,
        "fetched_at": fetched_at,
        "job_posting": {k: v for k, v in posting.items() if v},
        "page_meta": extract_page_meta(html),
        "parsed_from": "html",
    }


class MyJobMagExtractor(Extractor):
    source = "myjobmag"
    BASE = "https://www.myjobmag.co.ke"

    def __init__(self, listing_url: str | None = None, pages: int = 2):
        self.listing_url = listing_url or self.BASE + "/"
        self.pages = max(1, pages)
        self.http = PoliteSession()

    def _listing_pages(self) -> Iterator[str]:
        if self.listing_url.rstrip("/") == self.BASE:
            yield self.BASE + "/"
            for n in range(2, self.pages + 1):
                yield f"{self.BASE}/page/{n}"
        else:
            yield self.listing_url

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        self.seen = set()  # every posting on the listings we read = "seen today"
        handled: set[str] = set()
        fetched = 0
        for page_url in self._listing_pages():
            if fetched >= max_items:
                break
            try:
                listing = self.http.get(page_url)
            except RobotsDisallowed:
                log.warning("robots.txt disallows %s", page_url)
                continue
            for url in job_links(listing.text, self.BASE):
                self.seen.add(url)
                if fetched >= max_items or url in handled or already_done(url):
                    continue
                handled.add(url)
                try:
                    resp = self.http.get(url)
                except RobotsDisallowed:
                    log.warning("robots.txt disallows %s", url)
                    continue
                except Exception as exc:  # 403 / timeouts: log and move on, never work around
                    log.warning("failed %s: %s", url, exc)
                    continue
                record = parse_job_page(self.source, url, resp.text, utcnow().isoformat())
                if record is None:
                    log.warning("no job data found on %s", url)
                    continue
                fetched += 1
                yield Fetched(record=record, snapshot=resp.text, snapshot_id=url)
   