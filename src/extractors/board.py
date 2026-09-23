import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from src.extractors.jsonld import extract_job_posting
from src.utils.config import RAW_DIR
from src.utils.http import PoliteSession, RobotsDisallowed


def find_job_links(html, base_url, pattern):
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc
    links = []
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, a["href"]))[0]
        if pattern in url and urlparse(url).netloc == host and url != base_url and url not in links:
            links.append(url)
    return links


def save(source, url, html, posting):
    now = datetime.now(timezone.utc)
    out = RAW_DIR / f"source={source}" / f"dt={now:%Y-%m-%d}"
    out.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    meta = out / f"{key}.json"
    if meta.exists():  # idempotent: same URL, same day, no duplicate
        return False
    (out / f"{key}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))
    record = {
        "source": source,
        "url": url,
        "fetched_at": now.isoformat(),
        "job_posting": posting,
    }
    meta.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def run(source, listing_url, pattern, max_jobs):
    http = PoliteSession()
    listing = http.get(listing_url)
    links = find_job_links(listing.text, listing_url, pattern)[:max_jobs]
    print(f"Found {len(links)} job links")
    saved = skipped = failed = 0
    for url in links:
        try:
            resp = http.get(url)
        except RobotsDisallowed:
            print("robots.txt disallows:", url)
            skipped += 1
            continue
        except Exception as e:
            print("failed:", url, e)
            failed += 1
            continue
        posting = extract_job_posting(resp.text)
        if posting is None:
            print("no JobPosting JSON-LD:", url)
            failed += 1
            continue
        if save(source, url, resp.text, posting):
            saved += 1
        else:
            skipped += 1
    print(f"saved={saved} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("listing_url")
    ap.add_argument("--link-pattern", default="/listings/")
    ap.add_argument("--max", type=int, default=5)
    args = ap.parse_args()
    try:
        run(args.source, args.listing_url, args.link_pattern, args.max)
    except RobotsDisallowed as e:
        print("Blocked by robots.txt, not fetching:", e)
