"""Federal SAMHSA / 42 CFR Part 8 + TIP 63.

eCFR has a public, stable API. Two endpoints we use:
  * /api/versioner/v1/titles.json — gives us the latest issue date for title 42
  * /api/versioner/v1/full/{date}/title-42.xml?chapter=I&subchapter=A&part=8 — XML body

The /full/* endpoint only returns XML (not JSON), so we parse with lxml.
TIP 63 is a plain PDF — same pattern as the CMS booklet scrapers.
"""
from __future__ import annotations

import re

from .base import BaseScraper, ScrapeResult


class ECFRPart8Scraper(BaseScraper):
    """42 CFR Part 8 (Medications for Treatment of Opioid Use Disorder).

    We pull section-level XML, then emit one chunk per section with stable IDs so
    re-runs only re-embed sections that actually changed.
    """

    BASE = "https://www.ecfr.gov"

    def parse(self) -> ScrapeResult:
        issue_date = self._latest_title_42_issue_date()
        xml_url = (
            f"{self.BASE}/api/versioner/v1/full/{issue_date}/title-42.xml"
            f"?chapter=I&subchapter=A&part=8"
        )
        resp = self._get(xml_url, headers={"Accept": "application/xml"})
        raw_bytes = resp.content
        raw_path, digest = self._persist_raw(raw_bytes, suffix=".xml")

        sections = self._extract_sections(raw_bytes)
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "42 CFR Part 8",
                "issue_date": issue_date,
                "sections": sections,
                "section_count": len(sections),
            },
        )

    def _latest_title_42_issue_date(self) -> str:
        data = self.fetch_json(f"{self.BASE}/api/versioner/v1/titles.json")
        for t in data.get("titles", []):
            if t.get("number") == 42 or t.get("number") == "42":
                # eCFR returns ISO date string under 'latest_issue_date'.
                return t["latest_issue_date"]
        raise RuntimeError("eCFR titles.json did not include Title 42")

    @staticmethod
    def _extract_sections(xml_bytes: bytes) -> list[dict]:
        from lxml import etree  # lazy import

        root = etree.fromstring(xml_bytes)
        sections: list[dict] = []
        # eCFR wraps each section in <DIV8 TYPE="SECTION" N="8.x">. Some payloads use
        # lowercase / hierarchical tags — handle both.
        for div in root.iter():
            tag = etree.QName(div).localname.upper() if div.tag else ""
            if tag not in {"DIV8", "SECTION"}:
                continue
            type_attr = (div.get("TYPE") or "").upper()
            if tag == "DIV8" and type_attr and type_attr != "SECTION":
                continue
            n = div.get("N") or div.get("n") or ""
            heading_el = div.find(".//HEAD") if div.find(".//HEAD") is not None else div.find(".//head")
            heading = (heading_el.text or "").strip() if heading_el is not None else ""
            # Pull all descendant text — eCFR sections are short enough that we
            # don't need streaming.
            text = " ".join(t.strip() for t in div.itertext() if t and t.strip())
            sections.append({"id": n, "label": heading, "text": text})
        return sections


_TIP63_POLY_RE = re.compile(
    r"(?i)(benzodiazepine|alprazolam|polysubstance|alcohol\s+use|drank\s+alcohol)"
)


class SamhsaTIP63Scraper(BaseScraper):
    """SAMHSA TIP 63 — clinical safety guidelines around MAT polysubstance risk."""

    def parse(self) -> ScrapeResult:
        payload = self.fetch_bytes(self.source.url)
        raw_path, digest = self._persist_raw(payload, suffix=".pdf")
        text = self.pdf_to_text(payload)
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "SAMHSA TIP 63",
                "polysubstance_hits": _TIP63_POLY_RE.findall(text)[:50],
                "raw_excerpt": text[:2000],
                "full_text": text,  # consumed by the vector chunker
            },
        )
