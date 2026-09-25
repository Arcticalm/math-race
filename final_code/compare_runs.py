"""Select audited incumbents across reproducible solver runs without rescheduling."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from final_code.run_all import (
    digest, joint_score, package_versions, save_json, snapshot, transport_score,
    write_program_bundle,
)
from final_code.problem4.solver import q3_gate, read_q3


def collect(runs):
    q2, joint = [], []
    expected_inputs = None
    for root in runs:
        manifest = root / "manifest.json"
        cache = root / "communication_cache.json"
        if manifest.exists():
            inputs = json.loads(manifest.read_text())["input_sha256"]
        elif cache.exists():
            inputs = {key: value for key, value in json.loads(cache.read_text())["signature"].items()
                      if key.startswith("data/")}
        else:
            raise ValueError(f"Missing source input fingerprints: {root}")
        if not inputs or (expected_inputs is not None and inputs != expected_inputs):
            raise ValueError("Cannot compare runs with different source inputs")
        expected_inputs = inputs
        q2_path = root / "q2/validation.json"
        if q2_path.exists():
            metrics = json.loads(q2_path.read_text())
            if metrics.get("feasible") and metrics.get("terrain_clearance", {}).get("feasible"):
                q2.append((transport_score(metrics), root))
        if not q3_gate(root / "q3")["ready"]:
            continue
        read_q3(root / "q3")
        frozen_path = root / "q4/frozen_q3_sha256.json"
        if not frozen_path.exists() or json.loads(frozen_path.read_text()) != snapshot(root / "q3"):
            raise ValueError(f"Frozen Q3 hashes do not match: {root}")
        metrics = json.loads((root / "q3/screening.json").read_text())
        partition = json.loads((root / "q4/result.json").read_text())
        score = joint_score(metrics, partition)
        if score is not None:
            joint.append((score, root))
    if not q2 or not joint:
        raise ValueError("Need at least one audited Q2 and one certified Q3 with both frozen partitions")
    return q2, joint


def run(runs, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory")
    q2_candidates, joint_candidates = collect(runs)
    q2_score, q2_root = min(q2_candidates, key=lambda row: row[0])
    q3_score, q3_root = min(joint_candidates, key=lambda row: row[0])
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(q2_root / "q2", output / "q2")
    shutil.copytree(q3_root / "q3", output / "q3")
    shutil.copytree(q3_root / "q4", output / "q4")
    # Pattern IDs are local to a run; preserve source namespaces when combining
    # independent Q2 and Q3 incumbents from different search restarts.
    for index, root in enumerate(dict.fromkeys((q2_root, q3_root)), 1):
        provenance = output / "sources" / str(index)
        provenance.mkdir(parents=True, exist_ok=True)
        for name in ("patterns.json", "manifest.json", "feedback_history.json", "relay_locations.json"):
            if (root / name).exists():
                shutil.copy2(root / name, provenance / name)
        save_json(provenance / "origin.json", {"run": str(root.resolve())})
    result = {
        "feasible": True, "global_optimal": False,
        "q2": {"source": str(q2_root.resolve()), "score": q2_score},
        "q3_q4": {"source": str(q3_root.resolve()), "score": q3_score},
        "q2_candidates": [{"source": str(root.resolve()), "score": score} for score, root in q2_candidates],
        "joint_candidates": [{"source": str(root.resolve()), "score": score} for score, root in joint_candidates],
        "selection_rule": "independent time-first Q2; joint time, lateness, energy, sorties, K2+K3 deficit, resource sum, worst CV",
        "source_pattern_ids": "local to the recorded source run; no route, box, time or resource assignment changed",
        "packages": package_versions(),
        "artifact_sha256": {str(p.relative_to(output)): digest(p)
                            for folder in ("q2", "q3", "q4")
                            for p in (output / folder).iterdir() if p.suffix in (".csv", ".json", ".xlsx")},
    }
    save_json(output / "summary.json", result)
    write_program_bundle(output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.runs, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
