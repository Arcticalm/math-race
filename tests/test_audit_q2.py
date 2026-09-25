"""Regression tests for transport replay and optional Q4 restrictions."""

import copy
import unittest
from dataclasses import replace

from final_code.problem2.master import solve
from final_code.problem2.patterns import replay
from final_code.problem2.transport import RouteEvaluator, _validate, load_resources, load_task_boxes
from final_code.replay import left_shift_transport
from tests import test_final_code


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

    def test_continuous_compaction_preserves_feasibility(self):
        shifted = left_shift_transport([self.sortie], self.evaluator, self.batteries)[0]
        self.assertEqual(shifted.prep_start_s, 0.)
        self.assertLess(shifted.return_s, self.sortie.return_s)
        self.assertTrue(self.check(shifted)["feasible"])


if __name__ == "__main__":
    unittest.main()
