import argparse
import gzip
import hashlib
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from src.extractors.jsonld import extract_job_posting
from src.pipeline.ingest import ingest
from src.storage.raw_store import get_store
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


def html_key(source, url, day):
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return f"raw_html/source={source}/dt={day}/{h}.html.gz"


def run(source, listing_url, pattern, max_jobs, backend=None):
    store = get_store(backend)
    http = PoliteSession()
    listing = http.get(listing_url)
    links = find_job_links(listing.text, listing_url, pattern)[:max_jobs]
    print(f"Found {len(links)} job links")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records, snapshots = [], {}
    skipped = failed = 0
    for url in links:
        key = html_key(source, url, today)
        if store.exists(key):  # already fetched today: don't hit the site again
            skipped += 1
            continue
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
        records.append({
            "source": source,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "job_posting": posting,
        })
        snapshots[key] = resp.text

    inserted = 0
    if records:
        _, inserted = ingest(source, records, backend)  # raw JSONL, then Postgres
        # Snapshots are written LAST: they double as the "done today" marker, so a
        # crash before this point means the next run simply re-fetches those URLs.
        for key, html in snapshots.items():
            store.write(key, gzip.compress(html.encode("utf-8")))
    print(f"fetched={len(records)} new_rows={inserted} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("listing_url")
    ap.add_argument("--link-pattern", default="/listings/")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--backend", choices=["local", "s3"])
    args = ap.parse_args()
    try:
        run(args.source, args.listing_url, args.link_pattern, args.max, args.backend)
    except RobotsDisallowed as e:
        print("Blocked by robots.txt, not fetching:", e)