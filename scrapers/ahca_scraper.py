"""Florida AHCA Community Behavioral Health handbook + fee schedule scraper.

AHCA pages are partly JS-rendered and the static endpoint 403's on most cloud egress
IPs. Strategy:
  1. Try a polite plain `requests` fetch first (works from intern laptops).
  2. Fall back to Selenium (real Chrome UA, headless) when running in Azure Functions.
  3. From the rendered HTML, hunt for handbook + fee-schedule PDF links matching
     known title patterns. Persist every PDF found so a human can review on next QA.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

# AHCA loves changing their URL slugs. These patterns survive that.
HANDBOOK_PATTERNS = [
    re.compile(r"community[-\s_]?behavioral[-\s_]?health", re.I),
    re.compile(r"behavioral[-\s_]?health[-\s_]?services[-\s_]?handbook", re.I),
    re.compile(r"medication[-\s_]?assisted[-\s_]?treatment", re.I),
    re.compile(r"fee[-\s_]?schedule", re.I),
]


class AHCAHandbookScraper(BaseScraper):
    def parse(self) -> ScrapeResult:
        try:
            html = self.fetch_text(self.source.url)
        except Exception:
            # Selenium fallback for Cloudflare/JS gating.
            html = self._fetch_via_selenium(self.source.url)

        soup = BeautifulSoup(html, "lxml")
        candidate_links: list[dict] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            label = (a.get_text(strip=True) or href)[:200]
            if not href.lower().endswith(".pdf"):
                continue
            if not any(p.search(href + " " + label) for p in HANDBOOK_PATTERNS):
                continue
            candidate_links.append(
                {"label": label, "url": urljoin(self.source.url, href)}
            )

        # Pull each matching PDF so downstream stages can diff content, not just URLs.
        pdf_excerpts: dict[str, str] = {}
        warnings: list[str] = []
        for link in candidate_links:
            try:
                payload = self.fetch_bytes(link["url"])
                self._persist_raw(payload, suffix=".pdf")
                pdf_excerpts[link["url"]] = self.pdf_to_text(payload)[:4000]
            except Exception as exc:  # noqa: BLE001 — surface, don't crash the run
                warnings.append(f"AHCA PDF fetch failed {link['url']}: {exc}")

        raw_path, digest = self._persist_raw(html.encode("utf-8"), suffix=".html")
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "FL AHCA Community Behavioral Health",
                "candidate_links": candidate_links,
                "pdf_excerpts": pdf_excerpts,
            },
            warnings=warnings,
        )

    def _fetch_via_selenium(self, url: str) -> str:
        """Real-browser fallback. Imported lazily so test envs don't need Chrome."""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"--user-agent={self.session.headers['User-Agent']}")
        driver = webdriver.Chrome(options=opts)
        try:
            driver.get(url)
            driver.implicitly_wait(5)
            return driver.page_source
        finally:
            driver.quit()
