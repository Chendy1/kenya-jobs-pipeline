"""Is a JSON-LD salary actually visible on the page? Offline check on saved snapshots.
Usage: python scripts/check_salary_visibility.py
"""
import gzip
import json
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path("data/raw_html/source=brightermonday")


def walk(node):
    if isinstance(node, list):
        for item in node:
            yield from walk(item)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (list, dict)):
                yield from walk(v)


def job_salary(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for node in walk(data):
            if node.get("@type") == "JobPosting" and isinstance(node.get("baseSalary"), dict):
                val = node["baseSalary"].get("value") or {}
                return val.get("minValue"), val.get("maxValue")
    return None, None


def n(v):
    return int(float(v))


for path in sorted(ROOT.rglob("*.html.gz")):
    soup = BeautifulSoup(gzip.decompress(path.read_bytes()).decode("utf-8"), "html.parser")
    lo, hi = job_salary(soup)
    if lo is None or hi is None:
        continue
    title = (soup.h1.get_text(strip=True) if soup.h1 else path.name)[:42]
    for t in soup(["script", "style"]):
        t.decompose()
    lines = soup.get_text("\n", strip=True).splitlines()
    hits = [ln for ln in lines
            if len(ln) < 100 and any(f"{n(v):,}" in ln or str(n(v)) in ln for v in (lo, hi))]
    shown = "YES: " + hits[0] if hits else "NO"
    print(f"{title:<42} json-ld {n(lo):>7,}-{n(hi):<7,} on page? {shown}")