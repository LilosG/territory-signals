"""Polite downloads with a dated on-disk cache.

Downloads land in data/raw/<source_key>/<YYYY-MM-DD>/<filename>. A file already
cached for the run date is reused, so reruns do not hit the host again.
Conduct (per SOURCES.md): generic User-Agent with no personal contact details,
>= 2 s between requests per host (60 s where robots.txt sets Crawl-delay: 60),
robots.txt honoured, no logins or CAPTCHAs, backoff on 429/5xx.
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.robotparser
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
USER_AGENT = "territory-signals-pipeline/2.0"
DEFAULT_DELAY = 2.0
HOST_DELAY = {"gis-sangis1.hub.arcgis.com": 60.0, "www.sangis.org": 60.0}

_last_request: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _throttle(host: str) -> None:
    wait = HOST_DELAY.get(host, DEFAULT_DELAY) - (time.time() - _last_request.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)


def _robots_allows(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    host = parts.netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _throttle(host)
            r = requests.get(f"{parts.scheme}://{host}/robots.txt",
                             headers={"User-Agent": USER_AGENT}, timeout=30)
            _last_request[host] = time.time()
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                _robots[host] = rp
            else:  # no robots.txt (or unreadable): nothing disallows us
                _robots[host] = None
        except requests.RequestException:
            _robots[host] = None
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def raw_dir(source_key: str, run_date: date | None = None) -> Path:
    d = DATA_DIR / "raw" / source_key / (run_date or date.today()).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(source_key: str, url: str, filename: str | None = None,
             run_date: date | None = None, retries: int = 3) -> Path:
    """Download url into the dated cache (or return the cached copy)."""
    dest = raw_dir(source_key, run_date) / (filename or url.rsplit("/", 1)[-1])
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    host = urllib.parse.urlparse(url).netloc
    if not _robots_allows(url):
        raise PermissionError(f"robots.txt disallows {url}")
    part = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(retries):
        _throttle(host)
        try:
            with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True,
                              timeout=(30, 300)) as r:
                _last_request[host] = time.time()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                with open(part, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            part.rename(dest)
            return dest
        except (requests.RequestException, OSError) as exc:
            last_err = exc
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"download failed for {url}: {last_err}")
