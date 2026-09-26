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
from final_code.problem4.solver import PARTITION_POLICY, q3_gate, read_q3, validate_frozen_partition


def collect(runs):
    q2, joint = [], []
    expected_inputs = None
    expected_groups = None
    for root in runs:
        manifest = root / "manifest.json"
        if not manifest.exists() and (root / "summary.json").exists():
            origin = json.loads((root / "summary.json").read_text()).get("q3_q4", {}).get("provenance")
            if origin:
                manifest = root / origin / "manifest.json"
        cache = root / "communication_cache.json"
        groups = 0
        if manifest.exists():
            document = json.loads(manifest.read_text())
            inputs = document["input_sha256"]
            # A run keeps the Q3 scope it was launched with; its joint score must be
            # recomputed the same way, or coupled and independent runs would be
            # ranked on two different objectives.
            groups = int(document.get("parameters", {}).get("q3_partition_groups", 0))
        elif cache.exists():
            inputs = {key: value for key, value in json.loads(cache.read_text())["signature"].items()
                      if key.startswith("data/")}
        else:
            raise ValueError(f"Missing source input fingerprints: {root}")
        if not inputs or (expected_inputs is not None and inputs != expected_inputs):
            raise ValueError("Cannot compare runs with different source inputs")
        expected_inputs = inputs
        if expected_groups is not None and groups != expected_groups:
            raise ValueError("Cannot compare independent and coupled Q3 scopes or different partition group constraints")
        expected_groups = groups
        q2_path = root / "q2/validation.json"
        if q2_path.exists():
            metrics = json.loads(q2_path.read_text())
            if (metrics.get("feasible") and metrics.get("terrain_clearance", {}).get("feasible")
                    and metrics.get("audit_version") == "physical_replay_v2"):
                q2.append((transport_score(metrics), root))
        if not q3_gate(root / "q3")["ready"]:
            continue
        read_q3(root / "q3")
        frozen_path = root / "q4/frozen_q3_sha256.json"
        if not frozen_path.exists() or json.loads(frozen_path.read_text()) != snapshot(root / "q3"):
            raise ValueError(f"Frozen Q3 hashes do not match: {root}")
        metrics = json.loads((root / "q3/screening.json").read_text())
        if metrics.get("search", {}).get("required_partition_groups") != groups:
            raise ValueError(f"Q3 manifest and solver scopes disagree: {root}")
        partition = json.loads((root / "q4/result.json").read_text())
        validate_frozen_partition(root / "q3", partition)
        joint.append((joint_score(metrics, partition, groups > 0), root))
    if not q2 or not joint:
        raise ValueError("Need at least one audited Q2 and one certified Q3 whose task graph is frozen")
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
    provenance_paths = {}
    copied = {}
    for question, root in (("q2", q2_root), ("q3_q4", q3_root)):
        origin = root
        if (root / "summary.json").exists():
            previous = json.loads((root / "summary.json").read_text())
            relative = (previous.get(question) or {}).get("provenance")
            if relative:
                origin = root / relative
        if origin not in copied:
            relative = f"provenance/{len(copied) + 1}"
            provenance = output / relative
            provenance.mkdir(parents=True, exist_ok=True)
            for name in ("patterns.json", "manifest.json", "feedback_history.json", "relay_locations.json"):
                if (origin / name).exists():
                    shutil.copy2(origin / name, provenance / name)
            save_json(provenance / "origin.json", {"run": str(root.resolve()), "records": str(origin.resolve())})
            copied[origin] = relative
        provenance_paths[question] = copied[origin]
    partition = json.loads((output / "q4/result.json").read_text())
    result = {
        "feasible": True,
        "all_partitions_available": all(partition["solutions"][str(k)].get("feasible") for k in (2, 3)),
        "partition_policy": PARTITION_POLICY,
        "q3_partition_groups": json.loads((output / "q3/screening.json").read_text())["search"]["required_partition_groups"], "global_optimal": False,
        "q2": {"source": str(q2_root.resolve()), "provenance": provenance_paths["q2"], "score": q2_score},
        "q3_q4": {"source": str(q3_root.resolve()), "provenance": provenance_paths["q3_q4"], "score": q3_score},
        "q2_candidates": [{"source": str(root.resolve()), "score": score} for score, root in q2_candidates],
        "joint_candidates": [{"source": str(root.resolve()), "score": score} for score, root in joint_candidates],
        "selection_rule": "independent time-first Q2; joint time, lateness, energy and sorties, extended by the K=2/K=3 frozen-partition deficit, resource sum and worst CV only for coupled runs",
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
