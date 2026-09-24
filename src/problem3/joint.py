"""Joint transport and relay assignment helpers."""

from __future__ import annotations

from src.problem3.solver import select_relay_schedule


def coordinate_joint_schedule(sorties, relay_candidate_groups):
    """Select a resource-feasible relay cover for the supplied transport plan.

    Transport start coordination and relay candidate generation happen before
    this call. This function keeps those transport times fixed while solving the
    binary interval cover and resource assignment MILP.
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
        "method": "relay interval-cover MILP after transport start coordination",
        "feasible": bool(schedule["feasible_cover"]),
        "relay_schedule": {key: value for key, value in schedule.items() if key != "selected"},
        "transport_delays_s": {},
    }
    return (sorties if schedule["feasible_cover"] else None,
            schedule["selected"], metrics)
