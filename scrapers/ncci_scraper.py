"""CMS NCCI PTP edits — pulls the quarterly practitioner edit ZIP.

The landing page lists quarterly ZIPs. We:
  1. Pull the landing HTML.
  2. Find the most recent practitioner-PTP zip link.
  3. Download, persist, and extract the CSV inside.
  4. Filter rows to only the HCPCS codes Engine 1 evaluates (G-codes + H-codes from
     the MAT rule matrix) — keeps the downstream payload small.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

# Codes Engine 1 actually checks. Anything outside this set is noise for the matrix.
RELEVANT_CODES = {
    "G2067", "G2068", "G2069", "G2070", "G2071", "G2072", "G2073",
    "G2074", "G2075", "G0137",
    "H0020", "H0001", "H0004", "H0005", "H0006",
}

RE_PRACTITIONER_ZIP = re.compile(r"practitioner.*\.zip$", re.I)


class NCCIScraper(BaseScraper):
    def parse(self) -> ScrapeResult:
        html = self.fetch_text(self.source.url)
        soup = BeautifulSoup(html, "lxml")
        zip_urls = [
            urljoin(self.source.url, a["href"])
            for a in soup.find_all("a", href=True)
            if RE_PRACTITIONER_ZIP.search(a["href"])
        ]
        if not zip_urls:
            return ScrapeResult(
                source_key=self.source.key,
                source_name=self.source.name,
                fetched_at="",
                content_sha256="",
                raw_path="",
                parsed={"doc": "NCCI", "edits": []},
                warnings=["No practitioner PTP zip link found on landing page"],
            )

        zip_url = zip_urls[0]
        payload = self.fetch_bytes(zip_url)
        raw_path, digest = self._persist_raw(payload, suffix=".zip")

        edits = self._extract_relevant_edits(payload)
        return ScrapeResult(
            source_key=self.source.key,
            source_name=self.source.name,
            fetched_at="",
            content_sha256=digest,
            raw_path=str(raw_path),
            parsed={
                "doc": "NCCI PTP Edits (practitioner)",
                "source_zip": zip_url,
                "edit_count_relevant": len(edits),
                "edits": edits,
            },
        )

    @staticmethod
    def _extract_relevant_edits(payload: bytes) -> list[dict]:
        edits: list[dict] = []
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
            for name in csv_names:
                with zf.open(name) as fh:
                    text = io.TextIOWrapper(fh, encoding="latin-1", errors="ignore")
                    reader = csv.reader(text)
                    header: list[str] | None = None
                    for row in reader:
                        if not row:
                            continue
                        if header is None and "Column 1" in row[0] if row else False:
                            header = row
                            continue
                        # NCCI layout: column1, column2 are the paired codes.
                        if len(row) < 2:
                            continue
                        c1, c2 = row[0].strip(), row[1].strip()
                        if c1 in RELEVANT_CODES or c2 in RELEVANT_CODES:
                            edits.append({"column1": c1, "column2": c2, "raw": row[:9]})
        return edits
