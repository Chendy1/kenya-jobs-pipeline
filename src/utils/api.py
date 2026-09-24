"""Small JSON API client: retries with backoff, a minimum gap between calls, honest User-Agent."""
from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.config import CONTACT_EMAIL


class ApiClient:
    def __init__(self, min_interval: float = 1.0, timeout: int = 30):
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "POST"}), respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers["User-Agent"] = (
            f"kenya-jobs-pipeline/0.1 (personal portfolio project; contact: {CONTACT_EMAIL})")
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0

    def request(self, method: str, url: str, **kwargs) -> dict:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()