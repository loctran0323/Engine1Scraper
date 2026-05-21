"""Scrapers for CMS Internet-Only Manuals + MLN booklets.

These are PDF-hosted documents. We pull the PDF, extract text, and run a handful of
targeted regexes that map onto the rules the Engine 1 matrix actually cares about:
  - G-code bundle definitions (G2067-G2075)
  - IOP "9 services within 7 days" threshold tied to G0137
  - Documentation thresholds ("at least 1 service per 7 days")
"""
from __future__ import annotations

import re

from .base import BaseScraper, ScrapeResult

# --- shared regex catalog --------------------------------------------------------
# Anchored to vocabulary that's stable across CMS revisions. If CMS reshuffles a
# section, these patterns still light up — the structure of *what* they say
# changes much slower than *where* it lives.
RE_G_CODE = re.compile(r"\b(G20[67]\d)\b")  # G2067..G2079
RE_IOP_G0137 = re.compile(r"G0137[\s\S]{0,400}?(\d+)\s+(?:distinct\s+)?services?", re.I)
RE_WEEKLY_THRESHOLD = re.compile(
    r"(?:at\s+least|minimum\s+of)\s+(\d+)\s+services?\s+(?:per|every|in\s+a)\s+7[-\s]?day",
    re.I,
)
RE_TAKEHOME = re.compile(r"(take[-\s]?home|unsupervised)\s+(?:dose|medication)", re.I)


class _CMSPdfBase(BaseScraper):
    """Common machinery: pull PDF, extract text, persist, run a hook."""

    def parse(self) -> ScrapeResult:
        payload = self.fetch_bytes(self.source.url)
        raw_path, digest = self._persist_raw(payload, suffix=".pdf")
        text = self.pdf_to_text(payload)
        parsed = self._extract(text)
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",  # filled by run()
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed=parsed,
        )

    def _extract(self, text: str) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class CMSManualScraper(_CMSPdfBase):
    """Pub 100-02 Ch 17 OR Pub 100-04 Ch 39. Chooses extraction based on source key."""

    def _extract(self, text: str) -> dict:
        if self.source.key == "cms_pub_100_02_ch17":
            iop_match = RE_IOP_G0137.search(text)
            return {
                "doc": "Pub 100-02 Ch 17",
                "iop_threshold_services": int(iop_match.group(1)) if iop_match else None,
                "iop_window_days": 7 if iop_match else None,
                "g_codes_mentioned": sorted(set(RE_G_CODE.findall(text))),
                "raw_excerpt": text[:2000],
            }
        # default = 100-04 Ch 39
        weekly_match = RE_WEEKLY_THRESHOLD.search(text)
        return {
            "doc": "Pub 100-04 Ch 39",
            "weekly_bundle_min_services": int(weekly_match.group(1)) if weekly_match else 1,
            "g_codes_mentioned": sorted(set(RE_G_CODE.findall(text))),
            "raw_excerpt": text[:2000],
        }


class MLNBookletScraper(_CMSPdfBase):
    """MLN8296732 — OTP Medicare Billing & Payment booklet."""

    def _extract(self, text: str) -> dict:
        return {
            "doc": "MLN OTP Booklet",
            "g_codes_mentioned": sorted(set(RE_G_CODE.findall(text))),
            "mentions_take_home": bool(RE_TAKEHOME.search(text)),
            "raw_excerpt": text[:2000],
        }
