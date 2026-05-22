"""Map raw ScrapeResults to the Engine 1 JSON Rule Matrix.

The matrix shape is the contract the C# Desktop Agent reads. Field names match
the addendum table in the onboarding doc 1:1 so the agent's evaluator does not
need a translation layer.

Federal rules are emitted first, Florida-specific overrides second — matches the
"baseline before override" execution order required by Engine 1.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from scrapers.base import ScrapeResult

RULE_SCHEMA_VERSION = "2026.05.01"


def _rule(
    rule_id: str,
    payer_type: str,
    code: str,
    required_modifier: str | None,
    logic_type: str,
    *,
    source_key: str,
    extra: dict | None = None,
) -> dict:
    out = {
        "rule_id": rule_id,
        "payer_type": payer_type,
        "code": code,
        "required_modifier": required_modifier,
        "logic_type": logic_type,
        "source_key": source_key,
    }
    if extra:
        out["params"] = extra
    return out


# ---- per-source builders --------------------------------------------------------
def _from_pub_100_04(r: ScrapeResult) -> list[dict]:
    p = r.parsed
    return [
        _rule(
            "R-FED-01",
            "Medicare Advantage",
            "G2067",
            None,
            "BundleValidation",
            source_key=r.source_key,
            extra={
                "min_services_in_bundle": p.get("weekly_bundle_min_services", 1),
                "window_days": 7,
                "g_codes_in_scope": p.get("g_codes_mentioned", []),
            },
        )
    ]


def _from_pub_100_02(r: ScrapeResult) -> list[dict]:
    p = r.parsed
    threshold = p.get("iop_threshold_services")
    if not threshold:
        return []
    return [
        _rule(
            "R-FED-02",
            "Medicare",
            "G0137",
            None,
            "IopThresholdGuard",
            source_key=r.source_key,
            extra={
                "required_services": threshold,
                "window_days": p.get("iop_window_days", 7),
            },
        )
    ]


def _from_ahca(r: ScrapeResult) -> list[dict]:
    # The AHCA scraper produces handbook + fee-schedule excerpts. We emit the two
    # rules the addendum calls out by name; the source PDFs feed the diff-checker
    # so changes in modifier requirements get flagged for human review.
    return [
        _rule(
            "R-FL-02",
            "Managed Medicaid",
            "H0020",
            "POS-58",
            "PointOfCareBlock",
            source_key=r.source_key,
        ),
        _rule(
            "R-FL-03",
            "AHCA Medicaid",
            "ALL_SUD",
            "HF",
            "SubstanceAbuseModifier",
            source_key=r.source_key,
        ),
        _rule(
            "R-FL-04",
            "AHCA Medicaid",
            "H0020",
            "HD>HG",  # ordering rule: HD must precede HG when pregnancy ICD present
            "ModifierSequencer",
            source_key=r.source_key,
            extra={"trigger_icd_prefix": "O", "alt_modifier": "HG"},
        ),
    ]


def _from_ncci(r: ScrapeResult) -> list[dict]:
    edits = r.parsed.get("edits", [])
    rules: list[dict] = []
    for i, edit in enumerate(edits):
        rules.append(
            _rule(
                f"R-NCCI-{i:04d}",
                "Standard Clearinghouse",
                edit["column1"],
                None,
                "BundleGuard",
                source_key=r.source_key,
                extra={"mutually_exclusive_with": edit["column2"]},
            )
        )
    return rules


def _from_fcso(r: ScrapeResult) -> list[dict]:
    return [
        _rule(
            "R-FLMAC-01",
            "Medicare",
            "G2067",
            None,
            "PayerBlocker",
            source_key=r.source_key,
            extra={
                "enforce_g_codes": r.parsed.get("g_codes_mentioned", []),
                "block_standard_hcpcs": True,
            },
        )
    ]


def _from_sunshine(r: ScrapeResult) -> list[dict]:
    # Addendum: "Write JSON constraint enforcing an F11.2x (Opioid dependence)
    # diagnosis presence whenever MAT H-codes are billed."
    p = r.parsed
    if not p.get("requires_dx_with_h_codes"):
        return []
    return [
        _rule(
            "R-SUNSHINE-01",
            "Sunshine MCO",
            "H0020",
            None,
            "DiagnosisRequired",
            source_key=r.source_key,
            extra={
                "required_dx_prefix": "F11.2",
                "h_codes_in_scope": p.get("h_codes_referenced", [])[:25],
            },
        )
    ]


def _from_simply(r: ScrapeResult) -> list[dict]:
    # Addendum: "Implement regex scanner for txt_ClinicalNarrative time values;
    # trigger block/warning if < 15 mins is documented."
    threshold = r.parsed.get("min_counseling_threshold_minutes")
    return [
        _rule(
            "R-SIMPLY-01",
            "Simply MCO",
            "COUNSELING",
            None,
            "CounselingTimeMinimum",
            source_key=r.source_key,
            extra={"min_minutes": threshold or 15},
        )
    ]


_DISPATCH = {
    "cms_pub_100_04_ch39": _from_pub_100_04,
    "cms_pub_100_02_ch17": _from_pub_100_02,
    "fl_ahca_cbh_handbook": _from_ahca,
    "cms_ncci_edits": _from_ncci,
    "fl_mac_fcso_otp": _from_fcso,
    "sunshine_provider_manual": _from_sunshine,
    "simply_provider_resources": _from_simply,
}


def build_rule_matrix(results: Iterable[ScrapeResult]) -> dict:
    """Return the full Engine 1 matrix payload (federal first, FL second)."""
    federal_keys = {
        "cms_pub_100_04_ch39",
        "cms_pub_100_02_ch17",
        "cms_mln_otp_booklet",
    }
    federal_rules: list[dict] = []
    florida_rules: list[dict] = []
    sources_seen: list[dict] = []

    for r in results:
        builder = _DISPATCH.get(r.source_key)
        if builder is None:
            continue
        # Don't fabricate rules from a scrape that didn't actually fetch anything.
        # If you want a permanent fallback rule when a source is unreachable, it
        # belongs in a hand-curated "baseline.json", not the auto-built matrix.
        if any("scrape_failed" in w for w in r.warnings) or not r.parsed:
            continue
        bucket = federal_rules if r.source_key in federal_keys else florida_rules
        bucket.extend(builder(r))
        sources_seen.append(
            {
                "source_key": r.source_key,
                "content_sha256": r.content_sha256,
                "fetched_at": r.fetched_at,
            }
        )

    return {
        "schema_version": RULE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": federal_rules + florida_rules,
        "rule_count": len(federal_rules) + len(florida_rules),
        "sources": sources_seen,
    }
