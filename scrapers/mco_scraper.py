"""Florida MCO (Managed Care Organization) provider manuals.

Two MCOs are in scope per the addendum: Sunshine Health and Simply Healthcare.
Both publish provider manuals as large PDFs. We pull each, extract text, then
search for the rule triggers Engine 1 cares about per the addendum:

  Sunshine: "H-codes require matching diagnoses" → look for F11.2x (Opioid
            dependence) presence requirements alongside H-codes.
  Simply:   "Strict counseling documentation" → look for time-based counseling
            thresholds (15 minutes is the addendum's example).
"""
from __future__ import annotations

import re

from .base import BaseScraper, ScrapeResult

RE_F11 = re.compile(r"\bF11\.\d{1,3}[A-Z]?\b")
RE_H_CODE = re.compile(r"\b(H\d{4})\b")
RE_COUNSELING_TIME = re.compile(
    r"(\d{1,3})\s*(?:minute|min)\b.{0,80}?(?:counsel|therap|session)", re.I
)


class SunshineProviderManualScraper(BaseScraper):
    """Centene-owned Sunshine Health — FL Managed Medical Assistance plan."""

    def parse(self) -> ScrapeResult:
        payload = self.fetch_bytes(self.source.url)
        raw_path, digest = self._persist_raw(payload, suffix=".pdf")
        text = self.pdf_to_text(payload)

        f11_hits = sorted(set(RE_F11.findall(text)))
        h_codes = sorted(set(RE_H_CODE.findall(text)))
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "Sunshine Health Provider Manual",
                "f11_dx_codes_referenced": f11_hits,
                "h_codes_referenced": h_codes,
                "requires_dx_with_h_codes": bool(f11_hits and h_codes),
                "raw_excerpt": text[:2000],
                "full_text": text,
            },
        )


class SimplyProviderManualScraper(BaseScraper):
    """Simply Healthcare Plans — FL Healthy Kids / SMMC plan."""

    def parse(self) -> ScrapeResult:
        payload = self.fetch_bytes(self.source.url)
        raw_path, digest = self._persist_raw(payload, suffix=".pdf")
        text = self.pdf_to_text(payload)

        counseling_thresholds = [
            int(m) for m in RE_COUNSELING_TIME.findall(text) if m.isdigit()
        ]
        # Engine 1's addendum example: warn if counseling < 15 mins documented.
        min_threshold = min(counseling_thresholds) if counseling_thresholds else None
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "Simply Healthcare Provider Manual",
                "counseling_time_thresholds_minutes": sorted(set(counseling_thresholds)),
                "min_counseling_threshold_minutes": min_threshold,
                "raw_excerpt": text[:2000],
                "full_text": text,
            },
        )
