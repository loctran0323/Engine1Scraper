"""CMS NCCI PTP edits — pulls the quarterly practitioner edit ZIP.

We:
  1. Pull the landing HTML and find the most recent practitioner-PTP zip link.
  2. Download the zip, extract the *tab-delimited* additions/deletions files
     (NCCI calls them .txt but they're TSV, not CSV).
  3. Filter rows to HCPCS codes Engine 1 evaluates (OTP G/H-codes).

Files inside the ZIP look like:
    MCR_NCCI_Additions_Eff_<QTR>.txt
    MCR_NCCI_Deletions_Eff_<QTR>.txt
    MCR_NCCI_CCMIChgs_Eff_<QTR>.txt
    MCR_NCCI_Changes_Eff_<QTR>.xlsx  (we skip xlsx for now — additions/deletions cover it)
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult

# HCPCS codes Engine 1 evaluates. Expanded to cover the full OTP weekly bundle
# range (G2067–G2080) plus take-home naloxone codes (G1028, G2215) and the
# core FL Medicaid H-codes.
RELEVANT_CODES = {
    # OTP weekly bundle G-codes (CMS Pub 100-04 Ch 39)
    "G2067", "G2068", "G2069", "G2070", "G2071", "G2072", "G2073",
    "G2074", "G2075", "G2076", "G2077", "G2078", "G2079", "G2080",
    # OTP intake / add-on / take-home
    "G2086", "G2087", "G2088",
    "G1028", "G2215",          # take-home naloxone
    "G0137",                   # IOP threshold trigger
    # FL Medicaid MAT H-codes
    "H0001", "H0004", "H0005", "H0006", "H0020", "H0033", "H0047",
    "H0050", "H2010", "H2017",
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
            txt_names = [
                n for n in zf.namelist()
                if n.lower().endswith(".txt")
                and ("additions" in n.lower() or "deletions" in n.lower())
            ]
            for name in txt_names:
                file_kind = "addition" if "additions" in name.lower() else "deletion"
                with zf.open(name) as fh:
                    text = io.TextIOWrapper(fh, encoding="latin-1", errors="ignore")
                    # NCCI files are TAB-delimited, not comma. Their first row is a
                    # copyright blurb, then a header row spanning a few lines, then
                    # data rows: <Column1>\t<Column2>\t<ModifierIndicator>\t<...>.
                    reader = csv.reader(text, delimiter="\t")
                    for row in reader:
                        if len(row) < 2:
                            continue
                        c1, c2 = row[0].strip(), row[1].strip()
                        # Skip header / copyright rows (don't look like HCPCS codes).
                        if not _looks_like_hcpcs(c1) or not _looks_like_hcpcs(c2):
                            continue
                        if c1 in RELEVANT_CODES or c2 in RELEVANT_CODES:
                            edits.append(
                                {
                                    "column1": c1,
                                    "column2": c2,
                                    "modifier_indicator": (row[2].strip() if len(row) > 2 else ""),
                                    "edit_kind": file_kind,
                                    "source_file": name,
                                }
                            )
        return edits


_HCPCS_RE = re.compile(r"^[A-Z0-9]{5}$")


def _looks_like_hcpcs(code: str) -> bool:
    """HCPCS codes are 5 chars, alphanumeric (e.g., G2067, 99213, 0395T)."""
    return bool(_HCPCS_RE.match(code))
