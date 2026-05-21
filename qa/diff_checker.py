"""Phase 5: "Diff" checker — compare a new rule matrix against the live one.

The goal isn't a full bitwise diff (that would flag every regenerated timestamp).
We compare *rule semantics*: which rule_ids exist, which logic_type / modifier /
params changed. Output is small, reviewable, and safe to ship to Slack.

Why this matters: clinicians experience "alert fatigue" if rule changes silently
roll out at 2am. A diff that flags real semantic changes lets the team gate
deploys behind a human review for anything material.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from deepdiff import DeepDiff


@dataclass
class DiffReport:
    added_rule_ids: list[str] = field(default_factory=list)
    removed_rule_ids: list[str] = field(default_factory=list)
    changed_rules: list[dict] = field(default_factory=list)
    is_material: bool = False

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, default=str)


def _index(matrix: dict) -> dict[str, dict]:
    return {r["rule_id"]: r for r in matrix.get("rules", [])}


def diff_matrix(new_matrix: dict, live_matrix_path: Path | None) -> DiffReport:
    if live_matrix_path is None or not live_matrix_path.exists():
        # First deploy. Everything counts as "added" but nothing is *changed*.
        return DiffReport(
            added_rule_ids=[r["rule_id"] for r in new_matrix.get("rules", [])],
            is_material=True,
        )
    live = json.loads(live_matrix_path.read_text())
    new_idx, live_idx = _index(new_matrix), _index(live)

    added = sorted(set(new_idx) - set(live_idx))
    removed = sorted(set(live_idx) - set(new_idx))
    changed: list[dict] = []
    for rid in set(new_idx) & set(live_idx):
        delta = DeepDiff(
            live_idx[rid],
            new_idx[rid],
            ignore_order=True,
            # source_key shifting alone shouldn't be flagged as material.
            exclude_paths={"root['source_key']"},
        )
        if delta:
            changed.append({"rule_id": rid, "delta": json.loads(delta.to_json())})

    return DiffReport(
        added_rule_ids=added,
        removed_rule_ids=removed,
        changed_rules=changed,
        is_material=bool(added or removed or changed),
    )
