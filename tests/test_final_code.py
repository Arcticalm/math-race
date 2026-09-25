"""Behavior and packaging checks for the question-organized final code."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from final_code.package import write_program_bundle
from final_code.problem1.solver import Aircraft
from final_code.problem2.master import solve
from final_code.problem2.patterns import Pattern, replay
from final_code.problem2.transport import Battery, Drone, Sortie, TaskBox
from final_code.problem4.solver import _peak


class FinalCodeTests(unittest.TestCase):
    def setUp(self):
        aircraft = Aircraft("A", "test", 1, 100, 100, 1, 1000, 1000, 10, .2,
                            0, 0, 0, 0, 1, 1, 1, 0)
        self.evaluator = SimpleNamespace(aircrafts={"A": aircraft}, reserve=.2)
        self.boxes = [TaskBox(f"B{i}", f"S{i:03d}", "water", 1, .01, False,
                              None, 10000, 1) for i in range(1, 4)]
        self.drones = [Drone("U01", "A")]
        self.batteries = [Battery("A-B01", "A", 100)]

    def pattern(self, code, boxes, duration):
        route = list(dict.fromkeys(box.site for box in boxes))
        visits = ["O01", *route, "O01"]
        legs = [{"from": start, "to": end, "flight_s": duration / (len(visits) - 1)}
                for start, end in zip(visits, visits[1:])]
        sortie = Sortie(code, "A", boxes, route, len(boxes), .01 * len(boxes),
                        1, duration, battery_soc_return_percent=90, legs=legs)
        sortie = replay(sortie, self.evaluator)
        return Pattern(code, sortie, duration, 0, sortie.deliveries)

    def test_question_two_selects_mixed_patterns(self):
        a, b, c = self.boxes
        pool = [self.pattern("AB", [a, b], 8), self.pattern("C", [c], 9),
                self.pattern("A", [a], 2), self.pattern("BC", [b, c], 8),
                self.pattern("B", [b], 2)]
        result, _ = solve(pool, self.boxes, self.drones, self.batteries,
                          self.evaluator, time_limit=2)
        self.assertEqual({sortie.code for sortie in result["sorties"]}, {"A", "BC"})

    def test_question_three_reselects_with_communication_constraint(self):
        a, b, c = self.boxes
        pool = [self.pattern("fast", [a], 1), self.pattern("slow", [a], 2),
                self.pattern("B", [b], 1), self.pattern("C", [c], 1)]
        q2, _ = solve(pool, self.boxes, self.drones, self.batteries,
                      self.evaluator, time_limit=2)
        profiles = {pattern.code: [] for pattern in pool}
        profiles["fast"] = [{"start": 0, "end": 1, "locations": []}]
        candidate = dict(preflight_s=0, return_flight_s=0, fixed_energy_kwh=.1)
        q3, _ = solve(pool, self.boxes, self.drones, self.batteries,
                      self.evaluator, profiles=profiles, locations=[candidate],
                      max_relays=0, time_limit=2, hint=q2["sorties"])
        self.assertIn("fast", {sortie.code for sortie in q2["sorties"]})
        self.assertEqual({sortie.code for sortie in q3["sorties"]}, {"slow", "B", "C"})

    def test_question_four_uses_half_open_resource_intervals(self):
        self.assertEqual(_peak([(0, 10), (10, 20)]), 1)
        self.assertEqual(_peak([(0, 10), (9, 20)]), 2)

    def test_bundle_contains_all_four_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "program.zip"
            write_program_bundle(archive_path)
            with ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                for name in ("final_code/problem1/solver.py", "final_code/problem2/run.py",
                             "final_code/problem3/run.py", "final_code/problem4/solver.py",
                             "final_code/run_all.py", "docs/结果提交模板.xlsx"):
                    self.assertIn(name, archive.namelist())


if __name__ == "__main__":
    unittest.main()
