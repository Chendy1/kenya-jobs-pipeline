"""Remotive: official free public API for remote jobs (remotive.com).

Terms (read directly from https://github.com/remotive-com/remote-jobs-api on 2026-09-25):
  - free, no API key needed
  - link back to the Remotive URL and credit Remotive as the source when displaying jobs
  - do not resubmit Remotive jobs to other job boards
  - do not call too frequently (their own guidance: about 4 calls/day is plenty)
  - jobs are delayed 24h by Remotive itself, nothing we need to do about that

This project shows only aggregates plus outbound links (dw.v_public_jobs), so the
attribution requirement is already met structurally by how the app displays results.

Remote jobs are a different category from county-based listings: they are filtered to
roles open to Kenya/Africa/Worldwide candidates and should be read as "remote work
reachable from Kenya", not "jobs located in Kenya". Keep this out of county-based
analytics in dw.v_county_summary and friends.
"""
from __future__ import annotations

import os
from typing import Callable, Iterator

from src.extractors.base import Extractor, Fetched
from src.storage.raw_store import utcnow
from src.utils.api import ApiClient

URL = "https://remotive.com/api/remote-jobs"

# Only these candidate_required_location values count as "reachable from Kenya".
DEFAULT_LOCATION_KEYWORDS = ["kenya", "africa", "worldwide", "anywhere", "emea"]


class RemotiveExtractor(Extractor):
    source = "remotive"

    def __init__(self, search: str | None = None, category: str | None = None,
                keywords: list[str] | None = None):
        self.search = search or os.getenv("REMOTIVE_SEARCH")
        self.category = category or os.getenv("REMOTIVE_CATEGORY")
        env_kw = os.getenv("REMOTIVE_LOCATION_KEYWORDS", "")
        self.keywords = keywords or [k.strip().lower() for k in env_kw.split(",") if k.strip()] \
            or DEFAULT_LOCATION_KEYWORDS
        self.api = ApiClient(min_interval=1.0)

    def _relevant(self, job: dict) -> bool:
        loc = (job.get("candidate_required_location") or "").lower()
        return any(k in loc for k in self.keywords)

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        params = {}
        if self.search:
            params["search"] = self.search
        if self.category:
            params["category"] = self.category
        # One call returns the whole matching set; this endpoint has no pagination.
        body = self.api.request("GET", URL, params=params)
        jobs = body.get("jobs") or []
        got = 0
        for job in jobs:
            if got >= max_items:
                return
            if not self._relevant(job):
                continue
            url = job.get("url")
            if not url:
                continue
            yield Fetched(record={"source": self.source, "url": url,
                                  "fetched_at": utcnow().isoformat(), "job": job})
            got += 1