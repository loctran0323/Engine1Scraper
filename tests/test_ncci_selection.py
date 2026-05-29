"""Tests for NCCI full-table link selection + license-URL unwrapping.

These run offline against the real href patterns harvested from the live CMS
PTP edits page (2026-05). They guard the "repoint to full table" logic:
  - pick the practitioner full-table parts, not the hospital set or the delta;
  - pick the newest quarter+version and ALL of its parts, in order;
  - unwrap the AMA-license click-through to the direct /files/zip/ URL.
"""
from __future__ import annotations

import unittest

from scrapers.ncci_scraper import (
    RE_DELTA_PRACTITIONER,
    _medicaid_release_key,
    _resolve_cms_href,
    _select_full_table_parts,
    _select_medicaid_ptp_zips,
)

BASE = "https://www.cms.gov/medicare/coding-billing/ncci/ptp-edits"
MCD_BASE = "https://www.cms.gov/medicare/coding-billing/ncci-medicaid/medicaid-ncci-edit-files"

# Real hrefs from the live Medicaid edit-files page (2026-05): newest practitioner
# quarter, an older practitioner quarter (note the q/year order flips), and the
# DME set that must NOT be selected.
MCD_HREFS = [
    "/files/zip/medicaid-ncci-2026-q3-ptp-edits-practitioner-services.zip",
    "/files/zip/medicaid-ncci-2026-q3-ptp-edits-durable-medical-equipment.zip",
    "/files/zip/medicaid-ncci-q2-2026-ptp-edits-practitioner-services.zip",
]

# Real hrefs from the live page: q1 + q2, hospital + practitioner, plus the delta.
LIVE_HREFS = [
    "/files/zip/medicare-ncci-2026q2-practitioner-quarterly-additions-deletions-revisions-ptp.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q1-practitioner-ptp-edits-ccipra-v320r0-f1.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q1-practitioner-ptp-edits-ccipra-v320r0-f2.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q2-hospital-ptp-edits-ccioph-v321r0-f1.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q2-practitioner-ptp-edits-ccipra-v321r0-f1.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q2-practitioner-ptp-edits-ccipra-v321r0-f2.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q2-practitioner-ptp-edits-ccipra-v321r0-f3.zip",
    "/license/ama?file=/files/zip/medicare-ncci-2026q2-practitioner-ptp-edits-ccipra-v321r0-f4.zip",
]


class FullTableSelection(unittest.TestCase):
    def test_selects_newest_quarter_all_parts_in_order(self):
        parts = _select_full_table_parts(LIVE_HREFS, BASE)
        self.assertEqual(len(parts), 4)
        self.assertTrue(all("2026q2" in u and "ccipra" in u for u in parts))
        self.assertTrue(all("hospital" not in u for u in parts))
        self.assertEqual([u.rsplit("-", 1)[-1] for u in parts],
                         ["f1.zip", "f2.zip", "f3.zip", "f4.zip"])

    def test_ignores_older_quarter(self):
        parts = _select_full_table_parts(LIVE_HREFS, BASE)
        self.assertFalse(any("2026q1" in u for u in parts))

    def test_unwraps_license_to_direct_file_url(self):
        parts = _select_full_table_parts(LIVE_HREFS, BASE)
        self.assertTrue(
            parts[0].startswith("https://www.cms.gov/files/zip/"),
            f"license wrapper not stripped: {parts[0]}",
        )
        self.assertNotIn("/license/ama", parts[0])

    def test_normalizes_double_slash_in_target(self):
        url = _resolve_cms_href(
            "/license/ama?file=/files/zip//medicare-ncci-2026q2-hospital-ptp-edits-ccioph-v321r0-f3.zip",
            BASE,
        )
        self.assertNotIn("//medicare", url)

    def test_empty_when_no_full_table_links(self):
        self.assertEqual(_select_full_table_parts(LIVE_HREFS[:1], BASE), [])

    def test_delta_regex_matches_only_delta(self):
        self.assertTrue(RE_DELTA_PRACTITIONER.search(LIVE_HREFS[0]))
        self.assertFalse(RE_DELTA_PRACTITIONER.search(LIVE_HREFS[4]))


class MedicaidPtpSelection(unittest.TestCase):
    def test_selects_only_newest_quarter_practitioner_zip(self):
        urls = _select_medicaid_ptp_zips(MCD_HREFS, MCD_BASE)
        self.assertEqual(len(urls), 1)
        self.assertIn("2026-q3", urls[0])
        self.assertIn("practitioner", urls[0])

    def test_excludes_dme_and_older_quarter(self):
        urls = _select_medicaid_ptp_zips(MCD_HREFS, MCD_BASE)
        joined = " ".join(urls)
        self.assertNotIn("durable-medical-equipment", joined)
        self.assertNotIn("q2-2026", joined)

    def test_release_key_handles_both_date_orderings(self):
        self.assertEqual(_medicaid_release_key("x-2026-q3-y.zip"), (2026, 3))
        self.assertEqual(_medicaid_release_key("x-q2-2026-y.zip"), (2026, 2))

    def test_empty_when_no_practitioner_zip(self):
        self.assertEqual(
            _select_medicaid_ptp_zips(
                ["/files/zip/medicaid-ncci-2026-q3-ptp-edits-durable-medical-equipment.zip"],
                MCD_BASE,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
