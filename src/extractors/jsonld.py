"""Extract the JobPosting from a page's JSON-LD graph, plus page metadata."""
import json

from bs4 import BeautifulSoup


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        yield from _walk(node.get("@graph", []))


def _graph_index(soup) -> dict:
    """@id -> full node, for every node in every JSON-LD block on the page."""
    index = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            node_id = node.get("@id")
            if node_id and (node_id not in index or len(node) > len(index[node_id])):
                index[node_id] = node
    return index


def _resolve(value, index, depth=0):
    """Replace {'@id': X} references with the full node from the same page's graph."""
    if isinstance(value, list):
        return [_resolve(v, index, depth) for v in value]
    if not isinstance(value, dict):
        return value
    full = index.get(value.get("@id"))
    node = {**full, **value} if full is not None else dict(value)
    if depth < 2:
        node = {k: _resolve(v, index, depth + 1) for k, v in node.items()}
    return node


def extract_job_posting(html):
    soup = BeautifulSoup(html, "html.parser")
    index = _graph_index(soup)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            t = node.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                posting = dict(node)
                for field in ("hiringOrganization", "jobLocation"):
                    if field in posting:
                        posting[field] = _resolve(posting[field], index)
                return posting
    return None


def extract_page_meta(html) -> dict:
    """Raw strings only; the transform layer interprets them."""
    soup = BeautifulSoup(html, "html.parser")

    def meta(**attrs):
        tag = soup.find("meta", attrs=attrs)
        return tag.get("content") if tag and tag.get("content") else None

    return {
        "html_title": soup.title.get_text(strip=True) if soup.title else None,
        "og_title": meta(property="og:title"),
        "meta_description": meta(name="description"),
    }


def build_record(source, url, html, fetched_at):
    """The one place that defines what a raw record looks like (scraper and reparse share it)."""
    posting = extract_job_posting(html)
    if posting is None:
        return None
    return {
        "source": source,
        "url": url,
        "fetched_at": fetched_at,
        "job_posting": posting,
        "page_meta": extract_page_meta(html),
    }