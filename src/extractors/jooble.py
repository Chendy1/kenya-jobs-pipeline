"""Jooble official API (free key on request). An aggregator: snippets only, so link back."""
from __future__ import annotations

import os
from typing import Callable, Iterator

import requests

from src.extractors.base import Extractor, Fetched
from src.storage.raw_store import utcnow
from src.utils.api import ApiClient

DEFAULT_KEYWORDS = ["data analyst", "data engineer", "software developer"]


class JoobleExtractor(Extractor):
    source = "jooble"

    def __init__(self, keywords: list[str] | None = None, max_pages: int = 3):
        self.key = os.getenv("JOOBLE_API_KEY")
        if not self.key:
            raise RuntimeError("Set JOOBLE_API_KEY in .env (request a free key at https://jooble.org/api/about).")
        self.host = os.getenv("JOOBLE_API_HOST", "https://jooble.org").rstrip("/")
        env_kw = os.getenv("JOOBLE_KEYWORDS", "")
        self.keywords = keywords or [k.strip() for k in env_kw.split(";") if k.strip()] or DEFAULT_KEYWORDS
        self.max_pages = max_pages
        self.api = ApiClient(min_interval=1.0)

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        seen: set[str] = set()
        got = 0
        for keyword in self.keywords:
            for page in range(1, self.max_pages + 1):
                body = {"keywords": keyword, "location": "Kenya", "page": str(page)}
                try:
                    data = self.api.request("POST", f"{self.host}/api/{self.key}", json=body)
                except requests.RequestException as exc:
                    # the key is part of the URL: never let the URL reach a log or traceback
                    status = getattr(getattr(exc, "response", None), "status_code", "?")
                    raise RuntimeError(f"Jooble request failed (HTTP {status})") from None
                jobs = data.get("jobs") or []
                if not jobs:
                    break
                for job in jobs:
                    job_id = str(job.get("id") or job.get("link") or "")
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)
                    yield Fetched(record={"source": self.source, "job_id": job_id,
                                          "fetched_at": utcnow().isoformat(), "job": job})
                    got += 1
                    if got >= max_items:
                        return