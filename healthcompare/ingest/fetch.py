"""Download plan documents politely and keep a content-hashed manifest."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

USER_AGENT = "CoverCompareBot/0.1 (health insurance comparison research)"
DELAY_SECONDS = 2.0  # between requests to the same host


class Fetcher:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.manifest_path = cache_dir / "manifest.json"
        self.manifest: dict[str, dict] = (
            json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
            try:
                rp.read()
            except (urllib.error.URLError, OSError):
                rp = None  # robots.txt unreachable: proceed, as crawlers conventionally do
            self._robots[host] = rp
        rp = self._robots[host]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def fetch(self, plan_id: str, doc_type: str, url: str) -> dict:
        """Download one document; returns its manifest entry."""
        key = f"{plan_id}/{doc_type}"
        entry = {"url": url, "plan_id": plan_id, "doc_type": doc_type,
                 "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if not self.allowed(url):
            entry["status"] = "blocked_by_robots"
            self.manifest[key] = entry
            return entry

        host = urlsplit(url).netloc
        wait = DELAY_SECONDS - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except (urllib.error.URLError, OSError) as e:
            entry["status"] = f"error: {e}"
            self.manifest[key] = entry
            return entry
        finally:
            self._last_hit[host] = time.monotonic()

        ext = ".pdf" if body[:4] == b"%PDF" or "pdf" in ctype else ".html"
        path = self.cache_dir / plan_id / f"{doc_type}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(body).hexdigest()
        previous = self.manifest.get(key, {}).get("sha256")
        path.write_bytes(body)
        entry.update(status="ok", path=str(path.relative_to(self.cache_dir)), sha256=sha,
                     content_type=ctype, changed=previous is not None and previous != sha)
        self.manifest[key] = entry
        return entry

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self.manifest, indent=1, sort_keys=True))


def fetch_all(plans_json: Path, cache_dir: Path, only: str | None = None) -> list[dict]:
    plans = json.loads(plans_json.read_text())["plans"]
    f = Fetcher(cache_dir)
    results = []
    for p in plans:
        if only and p["id"] != only:
            continue
        for doc_type, url in p.get("documents", {}).items():
            results.append(f.fetch(p["id"], doc_type, url))
    f.save()
    return results
