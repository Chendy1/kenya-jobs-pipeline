"""ReliefWeb jobs (UN / NGO / humanitarian) via the official v2 API. Content belongs to the
publishing organisations: store and analyse it, link back, don't republish it."""
from __future__ import annotations

import os
from typing import Callable, Iterator

from src.extractors.base import Extractor, Fetched
from src.storage.raw_store import utcnow
from src.utils.api import ApiClient

FIELDS = ["title", "url", "body-html", "source.name", "country.name", "city.name",
          "date.created", "date.closing", "type.name", "career_categories.name",
          "experience.name", "theme.name"]


class ReliefWebExtractor(Extractor):
    source = "reliefweb"
    URL = "https://api.reliefweb.int/v2/jobs"

    def __init__(self, country: str = "Kenya", page_size: int = 100):
        self.appname = os.getenv("RELIEFWEB_APPNAME")
        if not self.appname:
            raise RuntimeError("Set RELIEFWEB_APPNAME in .env (request one at https://apidoc.reliefweb.int/).")
        self.country = country
        self.page_size = page_size
        self.api = ApiClient(min_interval=1.0)

    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        offset = got = 0
        while got < max_items:
            body = {
                "filter": {"field": "country.name", "value": self.country},
                "fields": {"include": FIELDS},
                "sort": ["date.created:desc"],
                "limit": min(self.page_size, max_items - got),
                "offset": offset,
            }
            data = self.api.request("POST", self.URL, params={"appname": self.appname}, json=body)
            items = data.get("data") or []
            if not items:
                return
            for item in items:
                fields = item.get("fields") or {}
                url = fields.get("url") or f"https://reliefweb.int/job/{item.get('id')}"
                yield Fetched(record={"source": self.source, "url": url, "reliefweb_id": item.get("id"),
                                      "fetched_at": utcnow().isoformat(), "job": fields})
                got += 1
                if got >= max_items:
                    return
            offset += len(items)