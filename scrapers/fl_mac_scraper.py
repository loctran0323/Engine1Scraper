"""FCSO (Florida Medicare Administrative Contractor) — OTP Fact Sheet."""
from __future__ import annotations

import re

from .base import BaseScraper, ScrapeResult

RE_G_CODE = re.compile(r"\b(G20[67]\d)\b")
RE_RATE = re.compile(r"\$\s?(\d{2,4}(?:\.\d{2})?)")


class FCSOFactSheetScraper(BaseScraper):
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
                "doc": "FCSO OTP Fact Sheet",
                "g_codes_mentioned": sorted(set(RE_G_CODE.findall(text))),
                "dollar_rates_found": RE_RATE.findall(text)[:50],
                "raw_excerpt": text[:2000],
            },
        )
