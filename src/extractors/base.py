"""The one interface every source implements."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Iterator


@dataclass
class Fetched:
    record: dict                      # raw payload; must carry url / job_id so the raw layer can key it
    snapshot: str | None = None       # optional raw page text (HTML sources), stored under raw_html/
    snapshot_id: str | None = None    # what to hash for the snapshot file name (usually the URL)


class Extractor(ABC):
    source: str  # must match its POLICY entry and (if custom) its adapter name

    @abstractmethod
    def fetch(self, max_items: int, already_done: Callable[[str], bool]) -> Iterator[Fetched]:
        """Yield at most max_items postings. HTML sources use already_done(snapshot_id)
        to skip pages that were already fetched today."""


def html_key(source: str, snapshot_id: str, day: str) -> str:
    h = hashlib.sha1(snapshot_id.encode()).hexdigest()[:16]
    return f"raw_html/source={source}/dt={day}/{h}.html.gz"