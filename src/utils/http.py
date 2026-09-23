import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.config import CONTACT_EMAIL

USER_AGENT = f"kenya-jobs-pipeline/0.1 (personal portfolio project; contact: {CONTACT_EMAIL})"


class RobotsDisallowed(Exception):
    pass


class PoliteSession:
    def __init__(self, min_delay=2.0):
        self.min_delay = min_delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._robots = {}
        self._last_request = {}

    def _robots_for(self, url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            resp = self.session.get(f"{base}/robots.txt", timeout=15)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                rp.parse([])  # no robots.txt means everything is allowed
            else:
                rp.parse(["User-agent: *", "Disallow: /"])  # server error: be cautious
            rp.modified()
            self._robots[base] = rp
        return self._robots[base]

    def get(self, url):
        rp = self._robots_for(url)
        if not rp.can_fetch(USER_AGENT, url):
            raise RobotsDisallowed(url)
        host = urlparse(url).netloc
        delay = max(self.min_delay, rp.crawl_delay(USER_AGENT) or 0)
        wait = self._last_request.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        resp = self.session.get(url, timeout=30)
        self._last_request[host] = time.monotonic()
        resp.raise_for_status()
        return resp
