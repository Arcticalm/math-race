import unittest
from types import SimpleNamespace

from src.problem21.solver import Sortie, TaskBox
from src.promble22.solve2.solver import exact_site_partitions


class SmallEvaluator:
    def __init__(self):
        self.aircrafts = {
            "A": SimpleNamespace(max_payload_kg=2, volume_m3=2,
                                 prep_s=0, load_each_s=0,
                                 handoff_base_s=0, handoff_each_s=0),
        }

    def evaluate(self, boxes, route, kind):
        if len(boxes) > 2:
            return None
        pair_energy = {
            frozenset(("A", "B")): 5,
            frozenset(("A", "C")): 3,
            frozenset(("B", "C")): 1,
        }
        energy = pair_energy.get(frozenset(box.code for box in boxes), 4)
        return Sortie("", kind, boxes, route, len(boxes), len(boxes), energy, 100)


class ExactSitePartitionTests(unittest.TestCase):
    def test_two_sortie_partition_picks_best_pair(self):
        boxes = [TaskBox(code, "S001", "普通", 1, 1, False, None, None, 1)
                 for code in ("A", "B", "C")]
        solutions = exact_site_partitions(boxes, SmallEvaluator())
        chosen = solutions["minimum_sorties"]
        self.assertEqual(len(chosen), 2)
        self.assertEqual({box.code for route in chosen for box in route.boxes}, {"A", "B", "C"})
        self.assertEqual(sum(route.energy_kwh for route in chosen), 5)
        self.assertIn({"B", "C"}, [{box.code for box in route.boxes} for route in chosen])


if __name__ == "__main__":
    unittest.main()
