"""JSearch (OpenWeb Ninja): licensed jobs API. Free tier = 200 requests/month, hard limit.

Each page is one request, so the per-run cap (JSEARCH_MAX_REQUESTS, default 4) is spread across
queries to keep a daily schedule inside the monthly allowance."""
from __future__ import annotations

import os
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
                    job_id = job.get("job_id")
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)
                    # "6 days ago" changes every day and would create a new raw version daily
                    job = {k: v for k, v in job.items() if k != "job_posted_at"}
                    yield Fetched(record={"source": self.source, "job_id": job_id,
                                          "fetched_at": utcnow().isoformat(), "job": job})
                    got += 1
                    if got >= max_items:
                        return
                if not cursor or not jobs:
                    break