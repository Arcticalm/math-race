"""Regression tests for transport replay and optional Q4 restrictions."""

import copy
import unittest
from dataclasses import replace

from final_code.problem2.master import solve
from final_code.problem2.patterns import replay
from final_code.problem2.transport import RouteEvaluator, _validate, load_resources, load_task_boxes
from final_code.replay import left_shift_transport
from final_code.run_all import joint_score
from tests import test_final_code


def _metrics(makespan=100.0):
    return {"joint_makespan_s": makespan,
            "transport_validation": {"weighted_all_expected_tardiness": 1.0},
            "joint_energy_kwh": 5.0, "total_sortie_count": 4}


def _partition(k3_feasible=True, score=(0, 10, 0.5)):
    return {"solutions": {"2": {"feasible": True, "score": score},
                          "3": {"feasible": k3_feasible, "score": score if k3_feasible else None,
                                "reason": "no relay-safe partition"}}}


class MasterAuditTests(unittest.TestCase):
    setUp = test_final_code.FinalCodeTests.setUp
    pattern = test_final_code.FinalCodeTests.pattern

    def test_pure_q3_does_not_impose_three_groups(self):
        pool = [self.pattern("all", self.boxes, 1)]
        pool += [self.pattern(str(i), [box], 2) for i, box in enumerate(self.boxes)]
        profiles = {pattern.code: [] for pattern in pool}
        result, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                          profiles=profiles, locations=[], time_limit=2)
        self.assertEqual([sortie.code for sortie in result["sorties"]], ["all"])
        grouped, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                           profiles=profiles, locations=[], time_limit=2, partition_groups=3)
        self.assertNotIn("all", {sortie.code for sortie in grouped["sorties"]})

    def test_independent_q3_score_ignores_frozen_partition(self):
        # In the independent scope a Q4 outcome must not re-rank two Q3 schedules.
        better_q3, worse_q3 = _metrics(100.0), _metrics(200.0)
        partition = _partition(score=(0, 10, 0.5))
        self.assertEqual(joint_score(better_q3, partition), joint_score(better_q3, partition, False))
        self.assertLess(joint_score(better_q3, partition), joint_score(worse_q3, partition))
        self.assertEqual(len(joint_score(better_q3, partition)), 4)

    def test_unrealisable_partition_never_ranks_as_feasible(self):
        partition = _partition(k3_feasible=False)
        # Fixed arity keeps rounds comparable, and a K that cannot be frozen is
        # ordered after a schedule whose K=2 and K=3 both exist.
        self.assertEqual(len(joint_score(_metrics(), partition, True)), 8)
        self.assertLess(joint_score(_metrics(), _partition(), True),
                        joint_score(_metrics(), partition, True))

    def test_missing_relay_locations_only_disable_patterns_needing_them(self):
        pool = [self.pattern("fast", [self.boxes[0]], 1)]
        pool += [self.pattern(str(i), [box], 2) for i, box in enumerate(self.boxes)]
        profiles = {pattern.code: [] for pattern in pool}
        profiles["fast"] = [{"start": 0, "end": 1, "locations": []}]
        result, _ = solve(pool, self.boxes, self.drones, self.batteries, self.evaluator,
                          profiles=profiles, locations=[], time_limit=2)
        self.assertIsNotNone(result)
        self.assertNotIn("fast", {sortie.code for sortie in result["sorties"]})


class TransportAuditTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = RouteEvaluator(.2, 1.)
        self.addCleanup(self.evaluator.close)
        self.drones, self.batteries = load_resources()
        for box in load_task_boxes():
            physical = self.evaluator.evaluate([box], [box.site], "A")
            if physical is not None:
                self.box = box
                self.sortie = replay(physical, self.evaluator, 10., "T")
                self.sortie.drone = next(d.code for d in self.drones if d.aircraft == "A")
                self.sortie.battery = next(b.code for b in self.batteries if b.aircraft == "A")
                break

    def check(self, sortie):
        return _validate([sortie], [self.box], self.drones, self.batteries, self.evaluator)

    def test_shortened_but_self_consistent_flight_is_rejected(self):
        sortie = copy.deepcopy(self.sortie)
        for leg in sortie.legs:
            leg["flight_s"] /= 2
        sortie.flight_s /= 2
        sortie = replay(sortie, self.evaluator, 10., "T")
        result = self.check(sortie)
        self.assertFalse(result["feasible"])
        self.assertTrue(any("physical flight duration" in error for error in result["violations"]))

    def test_changed_source_box_attributes_are_rejected(self):
        sortie = copy.deepcopy(self.sortie)
        sortie.boxes = [replace(self.box, priority=self.box.priority + 1)]
        self.assertFalse(self.check(sortie)["feasible"])

    def test_negative_start_is_rejected(self):
        sortie = replay(self.sortie, self.evaluator, -1., "T")
        self.assertFalse(self.check(sortie)["feasible"])

    def test_continuous_joint_refinement_removes_idle_time(self):
        from final_code.problem3.refine import refine_joint
        result, report = refine_joint({'sorties': [self.sortie], 'relays': []}, {},
                                     self.evaluator, [self.box], self.drones, self.batteries)
        self.assertTrue(report['accepted'])
        self.assertAlmostEqual(result['sorties'][0].prep_start_s, 0, places=6)
        self.assertTrue(self.check(result['sorties'][0])['feasible'])

    def test_continuous_compaction_preserves_feasibility(self):
        shifted = left_shift_transport([self.sortie], self.evaluator, self.batteries)[0]
        self.assertEqual(shifted.prep_start_s, 0.)
        self.assertLess(shifted.return_s, self.sortie.return_s)
        self.assertTrue(self.check(shifted)["feasible"])


if __name__ == "__main__":
    unittest.main()
