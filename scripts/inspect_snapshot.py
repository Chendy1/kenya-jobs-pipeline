"""Show what a saved page contains (offline, no web requests).
Usage: python scripts/inspect_snapshot.py <file.html.gz>
"""
import gzip
import json
import re
import sys

from bs4 import BeautifulSoup

html = gzip.decompress(open(sys.argv[1], "rb").read()).decode("utf-8")
soup = BeautifulSoup(html, "html.parser")

print("TITLE:", soup.title.get_text(strip=True) if soup.title else None)
print("H1   :", [h.get_text(" ", strip=True) for h in soup.find_all("h1")][:2])
for m in soup.find_all("meta"):
    if m.get("name") == "description" or m.get("property") == "og:title":
        print("META :", m.get("name") or m.get("property"), "=", str(m.get("content"))[:200])

print("\n--- JSON-LD nodes ---")
for tag in soup.find_all("script", type="application/ld+json"):
    try:
        data = json.loads(tag.string or "")
    except json.JSONDecodeError:
        print("(unparseable block)")
        continue
    nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
    for n in nodes:
        if isinstance(n, dict):
            print(n.get("@type"), "|", n.get("@id"), "| keys:", sorted(n.keys())[:14])
            for k in ("name", "legalName", "address", "url"):
                if k in n:
                    print("    ", k, "=", str(n[k])[:150])

print("\n--- links that look like company pages ---")
seen = set()
for a in soup.find_all("a", href=True):
    if re.search(r"/(company|companies|employer|employers|jobs-at)/", a["href"]) and a["href"] not in seen:
        seen.add(a["href"])
        print("  ", a.get_text(" ", strip=True)[:60], "->", a["href"])
    if len(seen) >= 8:
        break

print("\n--- elements with company/location-style class names ---")
count = 0
for el in soup.find_all(True):
    attrs = " ".join(el.get("class", [])) + " " + str(el.get("itemprop", "")) + " " + str(el.get("data-testid", ""))
    if re.search(r"company|employer|location|hiring|organi[sz]ation", attrs, re.I):
        text = el.get_text(" ", strip=True)
        if text and len(text) < 120:
            print("  <%s %s> %s" % (el.name, attrs.strip()[:60], text))
            count += 1
    if count >= 15:
        break

print("\n--- visible lines mentioning a place ---")
places = r"\b(Nairobi|Mombasa|Kisumu|Nakuru|Eldoret|Thika|Westlands|Kiambu|Machakos|Kajiado|Kenya)\b"
seen_lines = set()
for line in soup.get_text("\n", strip=True).splitlines():
    if re.search(places, line) and line not in seen_lines and len(line) < 120:
        seen_lines.add(line)
        print("  ", line)
    if len(seen_lines) >= 12:
        break