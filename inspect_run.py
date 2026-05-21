"""Quick inspector — print a human summary of the latest pipeline run.

Usage:
    python inspect_run.py           # summary of everything in data/
    python inspect_run.py <key>     # drill into one source (raw + parsed)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
VECTOR = ROOT / "data" / "vector"
DIFF = ROOT / "data" / "diffs"


def _hdr(title: str) -> None:
    print(f"\n{'=' * 6} {title} {'=' * 6}")


def summarize() -> None:
    _hdr("RAW PAYLOADS (data/raw/)")
    if not RAW.exists():
        print("  (none — pipeline hasn't run yet)")
    else:
        for sub in sorted(RAW.iterdir()):
            files = list(sub.iterdir())
            total = sum(f.stat().st_size for f in files)
            print(f"  {sub.name:30s} {len(files):3d} file(s)  {total/1024:8.1f} KB")

    _hdr("PARSED SCRAPER OUTPUT (data/processed/*.json)")
    if PROCESSED.exists():
        for f in sorted(PROCESSED.glob("*.json")):
            if f.name.startswith("engine1_matrix"):
                continue
            try:
                payload = json.loads(f.read_text())
                warns = payload.get("warnings") or []
                parsed = payload.get("parsed", {})
                status = "FAIL" if any("scrape_failed" in w for w in warns) else "OK"
                doc = parsed.get("doc", "?")
                hint = ""
                if "section_count" in parsed:
                    hint = f"sections={parsed['section_count']}"
                elif "edit_count_relevant" in parsed:
                    hint = f"edits={parsed['edit_count_relevant']}"
                elif "g_codes_mentioned" in parsed:
                    hint = f"g_codes={len(parsed['g_codes_mentioned'])}"
                print(f"  [{status}] {f.stem:30s} {doc:40s} {hint}")
                for w in warns:
                    print(f"         ↳ warning: {w}")
            except Exception as e:  # noqa: BLE001
                print(f"  [READ-ERR] {f.name}: {e}")

    _hdr("ENGINE 1 RULE MATRIX (data/processed/engine1_matrix.candidate.json)")
    cand = PROCESSED / "engine1_matrix.candidate.json"
    if cand.exists():
        m = json.loads(cand.read_text())
        print(f"  schema_version: {m['schema_version']}")
        print(f"  generated_at:   {m['generated_at']}")
        print(f"  rule_count:     {m['rule_count']}")
        print("  rules:")
        for r in m["rules"]:
            mod = r.get("required_modifier") or "-"
            print(f"    {r['rule_id']:14s} {r['payer_type']:24s} "
                  f"code={r['code']:10s} mod={mod:8s} logic={r['logic_type']}")
    else:
        print("  (no candidate matrix)")

    _hdr("ENGINE 2 RAG CHUNKS (data/vector/engine2_chunks.json)")
    chunks_path = VECTOR / "engine2_chunks.json"
    if chunks_path.exists():
        chunks = json.loads(chunks_path.read_text())
        by_source: dict[str, int] = {}
        for c in chunks:
            by_source[c["source_key"]] = by_source.get(c["source_key"], 0) + 1
        print(f"  total chunks: {len(chunks)}")
        for src, n in sorted(by_source.items()):
            print(f"    {src:30s} {n} chunks")

    _hdr("DIFF REPORT (data/diffs/latest.json)")
    diff_path = DIFF / "latest.json"
    if diff_path.exists():
        d = json.loads(diff_path.read_text())
        print(f"  material change: {d['is_material']}")
        print(f"  added:   {len(d['added_rule_ids'])} -> {d['added_rule_ids'][:5]}")
        print(f"  removed: {len(d['removed_rule_ids'])}")
        print(f"  changed: {len(d['changed_rules'])}")


def drill(source_key: str) -> None:
    f = PROCESSED / f"{source_key}.json"
    if not f.exists():
        print(f"No processed file for {source_key}. Run main.py first.")
        return
    payload = json.loads(f.read_text())
    print(json.dumps(payload, indent=2)[:5000])
    print("\n--- (truncated to first 5000 chars) ---")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        drill(sys.argv[1])
    else:
        summarize()
