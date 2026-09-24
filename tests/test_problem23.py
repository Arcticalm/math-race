import unittest

from src.problem23.solver import solve


class TimePriorityTests(unittest.TestCase):
    def test_selects_fastest_audited_candidate(self):
        sorties, metrics, boxes, candidates = solve()
        self.assertTrue(metrics["feasible"], metrics["violations"])
        self.assertEqual(len(boxes), 80)
        self.assertEqual(metrics["assigned_box_count"], 80)
        self.assertEqual(metrics["makespan_s"], min(
            item["metrics"]["makespan_s"] for item in candidates
        ))
        self.assertAlmostEqual(metrics["makespan_s"], max(sortie.return_s for sortie in sorties))
        self.assertEqual(metrics["hard_deadline_compliance_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
