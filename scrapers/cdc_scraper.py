"""CDC NCHS — ICD-10-CM Official Guidelines for Coding and Reporting (FY 2026).

Feeds Engine 2's NLP layer with SDOH Z-code definitions (Z55–Z65 series).
Pulls the PDF guidelines published by CDC NCHS each October, then extracts
the Z-code table so Engine 2 can recognize SDOH triggers in clinical notes.
"""
from __future__ import annotations

import re

from .base import BaseScraper, ScrapeResult

# Z-codes Engine 2 actively triggers on per the addendum's NLP rule matrix:
#   Z59.0x = Housing instability
#   Z59.82 = Transportation
#   Z56.x  = Employment
RE_SDOH_Z = re.compile(r"\bZ5[5-9]\.\d+x?\b|\bZ6[0-5]\.\d+x?\b")


class CDCICD10ZCodesScraper(BaseScraper):
    """ICD-10-CM Official Guidelines (FY 2026)."""

    def parse(self) -> ScrapeResult:
        payload = self.fetch_bytes(self.source.url)
        raw_path, digest = self._persist_raw(payload, suffix=".pdf")
        text = self.pdf_to_text(payload)

        z_codes = sorted(set(RE_SDOH_Z.findall(text)))
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "CDC ICD-10-CM Guidelines",
                "sdoh_z_codes_found": z_codes,
                "z_code_count": len(z_codes),
                "raw_excerpt": text[:2000],
                "full_text": text,  # consumed by RAG chunker
            },
        )
