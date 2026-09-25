"""Build an extractor by name. The policy check happens here, so nothing skips it."""
from __future__ import annotations

from src.extractors.base import Extractor
from src.extractors.policy import SourceNotAllowed, require_allowed


def _myjobmag(**kw) -> Extractor:
    from src.extractors.myjobmag import MyJobMagExtractor
    return MyJobMagExtractor(**kw)


def _reliefweb(**kw) -> Extractor:
    from src.extractors.reliefweb import ReliefWebExtractor
    return ReliefWebExtractor()


def _jsearch(**kw) -> Extractor:
    from src.extractors.jsearch import JSearchExtractor
    return JSearchExtractor()


def _jooble(**kw) -> Extractor:
    from src.extractors.jooble import JoobleExtractor
    return JoobleExtractor()

def _remotive(**kw) -> Extractor:
    from src.extractors.remotive import RemotiveExtractor
    return RemotiveExtractor()


FACTORIES = {"myjobmag": _myjobmag, "reliefweb": _reliefweb, "jsearch": _jsearch,"jooble": _jooble, "remotive": _remotive}


def available() -> list[str]:
    return sorted(FACTORIES)


def build(source: str, **opts) -> Extractor:
    require_allowed(source)
    if source not in FACTORIES:
        raise SourceNotAllowed(f"No extractor is implemented for '{source}' yet.")
    return FACTORIES[source](**opts)