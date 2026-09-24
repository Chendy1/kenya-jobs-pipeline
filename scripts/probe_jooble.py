"""Does Jooble return anything for Kenya? Makes at most 6 requests. Never prints the key."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()
key = os.environ["JOOBLE_API_KEY"]
hosts = ["https://jooble.org", "https://ke.jooble.org"]
queries = [("data analyst", "Kenya"), ("accountant", "Nairobi"), ("", "Kenya")]

for host in hosts:
    for keywords, location in queries:
        body = {"keywords": keywords, "location": location, "page": "1"}
        try:
            r = requests.post(f"{host}/api/{key}", json=body, timeout=30)
            try:
                data = r.json()
            except ValueError:
                data = {}
            print(f"{host:<24} kw={keywords!r:<16} loc={location!r:<10} "
                  f"HTTP {r.status_code} total={data.get('totalCount')} jobs={len(data.get('jobs') or [])}")
        except Exception as exc:
            print(f"{host:<24} kw={keywords!r} loc={location!r} failed: {type(exc).__name__}")