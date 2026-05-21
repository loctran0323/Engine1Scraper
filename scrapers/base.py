"""Base scraper: handles retries, polite headers, content-hashing, and on-disk caching.

Sub-classes implement `parse()` and return a `ScrapeResult`. The base class deals with
networking, so the scraper modules stay focused on extraction logic.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config import MAX_RETRIES, RAW_DIR, REQUEST_TIMEOUT_SECS, Source, USER_AGENT

log = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """One scrape pass. Persisted to disk + handed to the transformer stage."""

    source_key: str
    source_name: str
    fetched_at: str
    content_sha256: str
    raw_path: str
    # Whatever the parser pulled out. Structured per source — Engine 1 sources
    # return rule-shaped dicts, Engine 2 sources return chunked text dicts.
    parsed: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


class BaseScraper:
    def __init__(self, source: Source):
        self.source = source
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    # ---------- network ----------
    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential(min=1, max=10))
    def _get(self, url: str, **kwargs) -> requests.Response:
        log.info("GET %s", url)
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT_SECS, **kwargs)
        resp.raise_for_status()
        return resp

    # ---------- caching ----------
    def _persist_raw(self, payload: bytes, suffix: str) -> tuple[Path, str]:
        digest = hashlib.sha256(payload).hexdigest()
        out = RAW_DIR / self.source.key / f"{digest[:12]}{suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        return out, digest

    # ---------- helpers for sub-classes ----------
    def fetch_bytes(self, url: str) -> bytes:
        return self._get(url).content

    def fetch_text(self, url: str) -> str:
        return self._get(url).text

    def fetch_json(self, url: str) -> Any:
        return self._get(url, headers={"Accept": "application/json"}).json()

    @staticmethod
    def pdf_to_text(payload: bytes) -> str:
        # Lazy import so the package still imports even if pdfplumber isn't installed
        # in dev. Real runs (Azure Function) will have it.
        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)

    # ---------- public API ----------
    def run(self) -> ScrapeResult:
        result = self.parse()
        result.fetched_at = datetime.now(timezone.utc).isoformat()
        return result

    def parse(self) -> ScrapeResult:  # pragma: no cover - abstract
        raise NotImplementedError
