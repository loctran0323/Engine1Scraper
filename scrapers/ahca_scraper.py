"""Florida AHCA Community Behavioral Health handbook + fee schedule scraper.

The AHCA "Community Behavioral Health Services" landing page is largely
navigational — the actual coverage-policy handbook PDFs live under
`/content/download/<id>/file/<rule>.pdf` and are not linked from the landing
in a discoverable way.

Strategy:
  1. Fetch the landing HTML for record-keeping + future link discovery.
  2. Pull every known FL Medicaid behavioral-health coverage policy PDF directly
     by its rule number (these are stable — they're administrative rule IDs).
  3. Extract text from each PDF, search for HF / POS-58 / modifier mentions
     so the diff checker can flag changes to FL-specific requirements.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

# Known FL Medicaid behavioral-health coverage policies + MAT-specific docs.
# Each is a stable administrative rule ID (59G-4.xxx) or a dated PT bulletin.
# Verified live as of May 2026 via curl. The first two are MAT-specific — they
# contain the actual modifier/POS requirements Engine 1 enforces.
KNOWN_AHCA_PDFS: list[tuple[str, str]] = [
    # MAT-specific (highest priority for modifier rules)
    ("Coverage of Medication Assisted Treatment Drugs (PT 2021-25)",
     "https://ahca.myflorida.com/content/download/8134/file/PT_2021-25_Coverage.of.Medication.Assisted.Treatment.Drugs_07.23.2021.pdf"),
    ("Methadone Criteria",
     "https://ahca.myflorida.com/content/download/22818/file/Methadone_Criteria.pdf"),
    # Behavioral-health coverage policies (background context for RAG)
    ("Behavioral Health Assessment Services (59G-4.028)",
     "https://ahca.myflorida.com/content/download/5937/file/59G-4.028.pdf"),
    ("Behavioral Health Community Support Services (59G-4.031)",
     "https://ahca.myflorida.com/content/download/5939/file/59G-4.031.pdf"),
    ("Behavioral Health Therapy Services (59G-4.052)",
     "https://ahca.myflorida.com/content/download/5942/file/59G-4.052.pdf"),
    ("Specialized Therapeutic Services (59G-4.295)",
     "https://ahca.myflorida.com/content/download/5964/file/59G-4.295_Specialized_Therapeutic_Services_and_Limitations_Handbook_Adoption.pdf"),
    ("Behavioral Health Intervention Services (59G-4.370)",
     "https://ahca.myflorida.com/content/download/5968/file/59G-4.370.pdf"),
    ("Behavioral Health Overlay Services (59G-4.027)",
     "https://ahca.myflorida.com/content/download/27060/file/59G-4.027%20Behavioral%20Health%20Overlay%20Services%20Coverage%20and%20Limitations%20Handbook_Adoption.pdf"),
]

# Patterns we care about: modifier mentions that drive Engine 1 rules.
RE_HF = re.compile(r"\bHF\b\s*modifier|\bmodifier\s+HF\b", re.I)
RE_POS_58 = re.compile(r"POS[\s-]?58|place\s+of\s+service\s+58", re.I)
RE_HD_HG = re.compile(r"\bHD\b.*?\bHG\b|\bHG\b.*?\bHD\b", re.I | re.S)
RE_H_CODE = re.compile(r"\b(H\d{4})\b")


class AHCAHandbookScraper(BaseScraper):
    def parse(self) -> ScrapeResult:
        # 1. Pull the landing page (record-keeping + future link discovery).
        landing_html = ""
        landing_warnings: list[str] = []
        try:
            landing_html = self.fetch_text(self.source.url)
        except Exception as exc:  # noqa: BLE001
            try:
                landing_html = self._fetch_via_selenium(self.source.url)
            except Exception as exc2:  # noqa: BLE001
                landing_warnings.append(f"AHCA landing fetch failed: {exc} / {exc2}")

        if landing_html:
            self._persist_raw(landing_html.encode("utf-8"), suffix=".html")

        # Look for any future-discovered PDF links (in case AHCA adds them).
        discovered = self._discover_landing_pdfs(landing_html, self.source.url)

        # 2. Fetch every known direct PDF.
        handbooks: list[dict] = []
        warnings: list[str] = list(landing_warnings)
        all_urls = [*KNOWN_AHCA_PDFS, *[(label, url) for url, label in discovered]]
        seen: set[str] = set()
        for label, url in all_urls:
            if url in seen:
                continue
            seen.add(url)
            try:
                payload = self.fetch_bytes(url)
                self._persist_raw(payload, suffix=".pdf")
                text = self.pdf_to_text(payload)
                handbooks.append(
                    {
                        "label": label,
                        "url": url,
                        "char_count": len(text),
                        "mentions_HF_modifier": bool(RE_HF.search(text)),
                        "mentions_POS_58": bool(RE_POS_58.search(text)),
                        "mentions_HD_HG_pair": bool(RE_HD_HG.search(text)),
                        "h_codes_referenced": sorted(set(RE_H_CODE.findall(text))),
                        "excerpt": text[:1500],
                        "full_text": text,  # consumed by RAG chunker
                    }
                )
            except Exception as exc:  # noqa: BLE001 — surface, don't crash
                warnings.append(f"AHCA PDF fetch failed {url}: {exc}")

        # 3. Build the parsed payload.
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256="",  # multi-PDF source — no single hash
            raw_path="",
            parsed={
                "doc": "FL AHCA Community Behavioral Health",
                "handbook_count": len(handbooks),
                "handbooks": handbooks,
                "any_HF_mentioned": any(h["mentions_HF_modifier"] for h in handbooks),
                "any_POS_58_mentioned": any(h["mentions_POS_58"] for h in handbooks),
                "any_HD_HG_pair_mentioned": any(h["mentions_HD_HG_pair"] for h in handbooks),
            },
            warnings=warnings,
        )

    @staticmethod
    def _discover_landing_pdfs(html: str, base_url: str) -> list[tuple[str, str]]:
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        out: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            label = a.get_text(strip=True)[:200]
            if href.lower().endswith(".pdf") or "/content/download/" in href:
                if "windows" in label.lower() or "media" in label.lower():
                    continue  # filter the Windows Media Player junk link
                out.append((urljoin(base_url, href), label))
        return out

    def _fetch_via_selenium(self, url: str) -> str:
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
