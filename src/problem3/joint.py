"""Joint transport and relay assignment helpers."""

from __future__ import annotations

from src.problem3.solver import select_relay_schedule


def coordinate_joint_schedule(sorties, relay_candidate_groups):
    """Select a resource-feasible relay cover for the supplied transport plan.

    Transport start coordination is performed before candidate generation. This
    function keeps that plan unchanged and makes the relay selection contract
    explicit for the main solver.
    """
    declared_gap_ids = {
        int(gap["gap_id"])
        for group in relay_candidate_groups
        for gap in group.get("gaps", ())
        if "gap_id" in gap
    }
    candidate_gap_ids = {
        int(gap_id)
        for group in relay_candidate_groups
        for candidate in group.get("candidates", ())
        for gap_id in candidate.get("covered_gap_ids", ())
    }
    gap_count = max(declared_gap_ids | candidate_gap_ids, default=0)
    schedule = select_relay_schedule(relay_candidate_groups, gap_count)
    metrics = {
        "method": "transport plan fixed after sampled start coordination; relay cover solved by interval MILP",
        "feasible": bool(schedule["feasible_cover"]),
        "relay_schedule": {key: value for key, value in schedule.items() if key != "selected"},
        "transport_delays_s": {},
    }
    return (sorties if schedule["feasible_cover"] else None,
            schedule["selected"], metrics)
