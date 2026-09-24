"""JSearch (OpenWeb Ninja): licensed jobs API. Free tier = 200 requests/month, hard limit.

Each page is one request, so the per-run cap (JSEARCH_MAX_REQUESTS, default 4) is spread across
queries to keep a daily schedule inside the monthly allowance.

JSearch's job_id changes from one search to the next, so identity comes from the content
(employer + title + place). Fields that vary between calls are stored under "observed",
which the content hash ignores."""
from __future__ import annotations

import hashlib
import os
import re
from typing import Callable, Iterator

from src.extractors.base import Extractor, Fetched
from src.storage.raw_store import utcnow
from src.utils.api import ApiClient

DEFAULT_QUERIES = [
    "data analyst jobs in Kenya",
    "data engineer jobs in Kenya",
    "software developer jobs in Nairobi, Kenya",
    "jobs in Mombasa, Kenya",
]

# Stored with the record, ignored by the content hash (see VOLATILE_FIELDS in raw_store.py).
_OBSERVED = ("job_id", "job_google_link", "job_apply_link", "job_publisher", "apply_options",
             "job_posted_at_timestamp", "job_posted_at_datetime_utc")


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def fingerprint(job: dict) -> str | None:
    """Stable identity: the same employer + title + place is the same posting."""
    employer, title = _norm(job.get("employer_name")), _norm(job.get("job_title"))
    if not employer or not title:
        return None
    place = _norm(job.get("job_location") or job.get("job_city"))
    return hashlib.sha1(f"{employer}|{title}|{place}".encode()).hexdigest()[:20]


class JSearchExtractor(Extractor):
    source = "jsearch"
    URL = "https://api.openwebninja.com/jsearch/search-v2"
    USAGE_URL = "https://api.openwebninja.com/usage"

    def __init__(self, queries: list[str] | None = None, max_requests: int | None = None):
        key = os.getenv("JSEARCH_API_KEY")
        if not key:
            raise RuntimeError("Set JSEARCH_API_KEY in .env (free key: https://app.openwebninja.com/signup).")
        env_queries = os.getenv("JSEARCH_QUERIES", "")
        self.queries = queries or [q.strip() for q in env_queries.split(";") if q.strip()] or DEFAULT_QUERIES
        self.max_requests = int(max_requests or os.getenv("JSEARCH_MAX_REQUESTS") or 4)
        self.api = ApiClient(min_interval=1.0)
        self.api.session.headers["x-api-key"] = key

    def usage(self) -> dict | None:
        try:
            return self.api.request("GET", self.USAGE_URL, params={"api_id": "jsearch"}).get("data")
        except Exception:
            return None

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        seen: set[str] = set()
        used = got = 0
        per_query = max(1, self.max_requests // len(self.queries))
        for query in self.queries:
            cursor = None
            for _ in range(per_query):
                if used >= self.max_requests or got >= max_items:
                    return
                params = {"query": query, "country": "ke", "language": "en", "date_posted": "week"}
                if cursor:
                    params["cursor"] = cursor
                body = self.api.request("GET", self.URL, params=params)
                used += 1
                data = body.get("data")
                jobs = (data.get("jobs") if isinstance(data, dict) else data) or []
                cursor = (data.get("cursor") if isinstance(data, dict) else None) or body.get("cursor")
                for job in jobs:
                    key = fingerprint(job) or job.get("job_id")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    observed = {k: job[k] for k in _OBSERVED if k in job}
                    # "6 days ago" changes daily, so it is dropped rather than stored
                    stable = {k: v for k, v in job.items() if k not in _OBSERVED and k != "job_posted_at"}
                    yield Fetched(record={"source": self.source, "job_id": key,
                                          "fetched_at": utcnow().isoformat(),
                                          "observed": observed, "job": stable})
                    got += 1
                    if got >= max_items:
                        return
                if not cursor or not jobs:
                    break