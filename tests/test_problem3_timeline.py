import csv
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.problem3.timeline import load_problem23_schedule, overlapping_windows, solve_delays
from src.problem3.solver import build_trajectory

ROOT = Path(__file__).resolve().parents[1]


class TimelineTests(unittest.TestCase):
    def test_q23_replay_preserves_saved_times_routes_and_resources(self):
        directory = ROOT / "outputs/problem23/clearance50"
        sorties, boxes, source = load_problem23_schedule(directory)
        with (directory / "sorties_audit.csv").open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(source["strategy"], "constructive_merged/cp_sat")
        self.assertEqual(len(boxes), 80)
        for sortie, row in zip(sorties, rows):
            self.assertEqual(sortie.code, row["架次编号"])
            self.assertEqual(sortie.drone, row["无人机编号"])
            self.assertEqual(sortie.battery, row["电池编号"])
            self.assertEqual(sortie.prep_start_s, float(row["准备开始时刻（s）"]))
            self.assertAlmostEqual(sortie.return_s, float(row["返回O01时刻（s）"]))
        phases = build_trajectory(sorties)
        for sortie in sorties:
            track = [p for p in phases if p.sortie == sortie.code]
            self.assertAlmostEqual(track[0].start_s, sortie.takeoff_s)
            self.assertAlmostEqual(track[-1].end_s, sortie.return_s)
            for first, second in zip(track, track[1:]):
                self.assertAlmostEqual(first.end_s, second.start_s)
                self.assertAlmostEqual(first.end_altitude_m, second.start_altitude_m)

    def test_merge_requires_absolute_overlap_and_retains_singletons(self):
        gaps = [dict(gap_id=i, start_s=start, end_s=end) for i, start, end in
                [(1, 0, 10), (2, 5, 15), (3, 15, 20), (4, 5, 15)]]
        windows = {tuple(sorted(g["gap_id"] for g in w)) for w in overlapping_windows(gaps)}
        self.assertIn((1, 2, 4), windows)
        for i in range(1, 5):
            self.assertIn((i,), windows)
        self.assertFalse(any(3 in w and len(w) > 1 for w in windows))

    def test_relay_conflict_delays_transport_and_preserves_deadlines(self):
        sorties = [SimpleNamespace(code=f"T{i}", drone=f"U{i}", battery=f"B{i}",
            prep_start_s=0, prep_end_s=100, loading_end_s=120, takeoff_s=120,
            return_s=1000, battery_soc_return_percent=80, boxes=[], deliveries={})
            for i in range(3)]
        groups = [{"candidates": [dict(covered_gap_ids=[i + 1], covered_sorties=f"T{i}",
            preparation_start_s=0, service_start_s=300, service_end_s=500,
            return_o01_s=600, return_soc_percent=80, energy_kwh=0.5,
            longitude=i, latitude=0, hover_altitude_m=200) for i in range(3)],
            "gaps": [dict(gap_id=i+1, sortie=f"T{i}", start_s=300, end_s=500) for i in range(3)]}]
        batteries = [SimpleNamespace(code=f"B{i}", full_charge_s=1800) for i in range(3)]
        with patch("src.problem3.timeline.load_resources", return_value=([], batteries)):
            shifted, info = solve_delays(sorties, groups, 3, time_limit_s=5)
        self.assertIsNotNone(shifted, info)
        delays = sorted(s.prep_start_s for s in shifted)
        self.assertGreaterEqual(delays[-1], 900)
        self.assertTrue(all(t >= 0 for t in delays))
        self.assertTrue(all(s.prep_start_s == 0 for s in sorties))

    def test_no_schedule_when_relay_delay_would_break_hard_deadlines(self):
        boxes = [SimpleNamespace(code=f"BOX{i}", item_type="医疗物资", due_s=500,
                                 first_batch=False, first_deadline_s=None) for i in range(3)]
        sorties = [SimpleNamespace(code=f"T{i}", drone=f"U{i}", battery=f"B{i}",
            prep_start_s=0, prep_end_s=100, loading_end_s=120, takeoff_s=120,
            return_s=1000, battery_soc_return_percent=80, boxes=[boxes[i]],
            deliveries={boxes[i].code: 500}) for i in range(3)]
        groups = [{"candidates": [dict(covered_gap_ids=[i+1], covered_sorties=f"T{i}",
            preparation_start_s=0, service_start_s=300, service_end_s=500,
            return_o01_s=600, return_soc_percent=80, energy_kwh=0.5,
            longitude=i, latitude=0, hover_altitude_m=200) for i in range(3)],
            "gaps": [dict(gap_id=i+1, sortie=f"T{i}", start_s=300, end_s=500) for i in range(3)]}]
        batteries = [SimpleNamespace(code=f"B{i}", full_charge_s=1800) for i in range(3)]
        with patch("src.problem3.timeline.load_resources", return_value=([], batteries)):
            shifted, info = solve_delays(sorties, groups, 3, time_limit_s=5)
        self.assertIsNone(shifted)
        self.assertEqual(info["status"], "INFEASIBLE")

    def test_energy_component_overlap_is_audited_independently(self):
        from src.problem3.audit import audit_relay_resources
        from src.problem3.physics import LinkEvaluator, load_relay_parameters, estimate_relay_mission, sampled_flight_leg
        params = load_relay_parameters()
        evaluator = LinkEvaluator()
        try:
            base = evaluator.base
            terrain, distance = sampled_flight_leg(evaluator, base, base)
            altitude = base.elevation_m + 50
            estimate = estimate_relay_mission(100, distance, terrain, altitude,
                                              distance, terrain, base.elevation_m)
        finally:
            evaluator.close()
        service_start = params.preparation_s + estimate.outbound_flight_s + params.link_setup_s
        mission = dict(preparation_start_s=0, service_start_s=service_start,
            service_end_s=service_start+100, return_o01_s=service_start+100+estimate.return_flight_s,
            energy_kwh=estimate.energy_kwh, return_soc_percent=estimate.return_soc_percent,
            longitude=base.longitude, latitude=base.latitude, ground_dsm_m=base.elevation_m,
            hover_altitude_m=altitude, energy_component="RE-01")
        audit = audit_relay_resources([dict(mission, relay_drone="R01"), dict(mission, relay_drone="R02")])
        self.assertFalse(audit["feasible"])
        self.assertTrue(any(c.get("resource") == "RE-01" for c in audit["conflicts"]))

    def test_missing_spatial_candidate_is_not_fixed_by_arbitrary_delay(self):
        sorties, _, _ = load_problem23_schedule(ROOT / "outputs/problem23/clearance50")
        shifted, info = solve_delays(sorties, [], 1, time_limit_s=1)
        self.assertIsNone(shifted)
        self.assertEqual(info["impossible_gap_ids"], [1])


if __name__ == "__main__":
    unittest.main()
