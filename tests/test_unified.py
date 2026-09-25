"""Behavior tests for joint pattern selection, resource replay and freezing."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from scripts.unified.master import color_intervals, solve
from scripts.unified.patterns import Pattern, add_patterns, replay
from scripts.unified.solver import joint_score, snapshot
from src.problem1.solver import Aircraft
from src.problem21.solver import Battery, Drone, Sortie, TaskBox


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        aircraft = Aircraft("A", "test", 1, 100, 100, 1, 1000, 1000, 10, .2,
                            0, 0, 0, 0, 1, 1, 1, 0)
        self.evaluator = SimpleNamespace(aircrafts={"A": aircraft}, reserve=.2)
        self.boxes = [TaskBox(f"B{i}", f"S{i:03d}", "water", 1, .01, False, None, 10000, 1)
                      for i in range(1, 4)]
        self.drones = [Drone("U01", "A")]
        self.batteries = [Battery("A-B01", "A", 100)]

    def pattern(self, code, boxes, duration, energy=1, charge=0):
        route = list(dict.fromkeys(b.site for b in boxes))
        visits = ["O01", *route, "O01"]
        legs = [{"from": a, "to": b, "flight_s": duration / (len(visits) - 1)}
                for a, b in zip(visits, visits[1:])]
        sortie = Sortie(code, "A", boxes, route, len(boxes), .01 * len(boxes), energy,
                        duration, battery_soc_return_percent=90, legs=legs)
        sortie = replay(sortie, self.evaluator)
        return Pattern(code, sortie, duration, charge, sortie.deliveries)

    def test_selects_mixed_patterns_not_an_entire_preselected_grouping(self):
        a, b, c = self.boxes
        pool = [self.pattern("AB", [a, b], 8), self.pattern("C", [c], 9),
                self.pattern("A", [a], 2), self.pattern("BC", [b, c], 8),
                self.pattern("B", [b], 2)]
        result, search = solve(pool, self.boxes, self.drones, self.batteries,
                               self.evaluator, time_limit=2)
        self.assertEqual({s.code for s in result["sorties"]}, {"A", "BC"})
        self.assertEqual(search["integer_makespan_s"], 10)
        self.assertFalse(search["global_optimal"])
        self.assertEqual(sorted(b.code for s in result["sorties"] for b in s.boxes), ["B1", "B2", "B3"])

    def test_q3_reselects_when_fast_q2_pattern_has_no_communication_option(self):
        a, b, c = self.boxes
        pool = [self.pattern("fast", [a], 1), self.pattern("slow", [a], 2),
                self.pattern("B", [b], 1), self.pattern("C", [c], 1)]
        q2, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator, time_limit=2)
        self.assertIn("fast", {s.code for s in q2["sorties"]})
        profiles = {p.code: [] for p in pool}
        profiles["fast"] = [{"start": 0, "end": 1, "locations": []}]
        location = dict(preflight_s=0, return_flight_s=0, fixed_energy_kwh=.1)
        q3, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                      profiles=profiles, locations=[location], max_relays=0,
                      time_limit=2, hint=q2["sorties"])
        self.assertEqual({s.code for s in q3["sorties"]}, {"slow", "B", "C"})

    def test_battery_charge_is_not_released_with_airframe(self):
        pool = [self.pattern(str(i), [box], 2.25, charge=5.25) for i, box in enumerate(self.boxes)]
        result, _ = solve(pool, self.boxes, self.drones, self.batteries,
                          self.evaluator, time_limit=2)
        starts = sorted(s.prep_start_s for s in result["sorties"])
        self.assertGreaterEqual(starts[1] - starts[0], 7.5)
        self.assertGreaterEqual(starts[2] - starts[1], 7.5)

    def test_hard_due_is_conservative_not_rounded_up(self):
        box = replace(self.boxes[0], item_type="医疗物资", due_s=1.4)
        pool = [self.pattern("late", [box], 3)]
        result, search = solve(pool, [box], self.drones, self.batteries,
                               self.evaluator, time_limit=2)
        self.assertIsNone(result)
        self.assertEqual(search["status"], "INFEASIBLE")

    def test_q3_prevents_a_route_connecting_all_three_sites(self):
        pool = [self.pattern("all", self.boxes, 1)]
        pool += [self.pattern(str(i), [box], 2) for i, box in enumerate(self.boxes)]
        result, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                          profiles={p.code: [] for p in pool}, locations=[], time_limit=2)
        self.assertNotIn("all", {s.code for s in result["sorties"]})

    def test_joint_makespan_includes_relay_return_and_nonnegative_preparation(self):
        pool = [self.pattern(str(i), [box], 10) for i, box in enumerate(self.boxes)]
        profiles = {p.code: [] for p in pool}
        profiles["0"] = [{"start": 5, "end": 8, "locations": [0]}]
        location = dict(preflight_s=215., outbound_flight_s=5., return_flight_s=100.,
                        fixed_energy_kwh=.1, longitude=0., latitude=0.,
                        ground_dsm_m=0., hover_altitude_m=300., agl_m=300.)
        result, search = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                               profiles=profiles, locations=[location], max_relays=1,
                               time_limit=2)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["relays"]), 1)
        relay = result["relays"][0]
        self.assertGreaterEqual(relay["preparation_start_s"], 0.)
        self.assertGreater(relay["return_o01_s"], max(s.return_s for s in result["sorties"]))
        self.assertGreaterEqual(search["integer_makespan_s"], relay["return_o01_s"])
        self.assertEqual(relay["covered_sorties"], "0")

    def test_rejected_proposals_do_not_exhaust_expansion_budget(self):
        physical = {b.code: self.pattern(b.code, [b], 2).sortie for b in self.boxes[1:]}
        self.evaluator.evaluate = lambda boxes, route, kind: copy.deepcopy(physical.get(boxes[0].code))
        pool = []
        stats = add_patterns(pool, [([b], [b.site]) for b in self.boxes], self.evaluator,
                             self.batteries, max_accepted=1)
        self.assertEqual(stats, {"attempted_proposals": 2, "accepted_proposals": 1})
        self.assertEqual([b.code for p in pool for b in p.sortie.boxes], ["B2"])

    def test_interval_coloring_respects_half_open_endpoints(self):
        self.assertEqual(color_intervals([("a", 0, 2), ("b", 2, 3)], ["R"]), {"a": "R", "b": "R"})
        with self.assertRaises(ValueError):
            color_intervals([("a", 0, 2), ("b", 1, 3)], ["R"])

    def test_comparison_rejects_different_input_datasets(self):
        from scripts.unified.compare_runs import collect
        with tempfile.TemporaryDirectory() as temporary:
            roots = [Path(temporary) / name for name in ("a", "b")]
            for index, root in enumerate(roots):
                root.mkdir()
                (root / "manifest.json").write_text(json.dumps({"input_sha256": {"data/input": str(index)}}))
            with self.assertRaisesRegex(ValueError, "different source inputs"):
                collect(roots)

    def test_frozen_snapshot_detects_schedule_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "transport.csv").write_text("task,start\na,1\n")
            before = snapshot(path)
            (path / "transport.csv").write_text("task,start\na,2\n")
            self.assertNotEqual(before, snapshot(path))

    def test_candidate_requires_both_partitions_and_prefers_q3_metrics(self):
        metrics = dict(joint_makespan_s=10, joint_energy_kwh=1, total_sortie_count=2,
                       transport_validation={"weighted_all_expected_tardiness": 0})
        partition = {"solutions": {"2": {"feasible": True, "score": [0, 10, .2]}}}
        self.assertIsNone(joint_score(metrics, partition))
        partition["solutions"]["3"] = {"feasible": True, "score": [2, 12, .1]}
        better_time = copy.deepcopy(metrics)
        better_time["joint_makespan_s"] = 9
        self.assertLess(joint_score(better_time, partition), joint_score(metrics, partition))


if __name__ == "__main__":
    unittest.main()
