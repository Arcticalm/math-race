import copy
import unittest

from src.problem2.solver import (
    _charge_duration,
    _hard_deadlines,
    _validate,
    RouteEvaluator,
    load_resources,
    load_task_boxes,
    solve,
)


class ProblemTwoInputTests(unittest.TestCase):
    def test_workbooks_have_expected_tasks_and_inventory(self):
        boxes = load_task_boxes()
        drones, batteries = load_resources()
        self.assertEqual(len(boxes), 80)
        self.assertEqual(len({box.code for box in boxes}), 80)
        self.assertEqual(len(drones), 8)
        self.assertEqual(len(batteries), 14)


class ProblemTwoScheduleTests(unittest.TestCase):
    def test_charge_model_boundaries(self):
        self.assertAlmostEqual(_charge_duration(1000, 1.0), 0.0)
        self.assertAlmostEqual(_charge_duration(1000, 0.9), 350.0)
        self.assertAlmostEqual(_charge_duration(1000, 0.0), 1000.0)

    def test_medical_first_batch_box_keeps_both_hard_deadlines(self):
        box = next(box for box in load_task_boxes() if box.item_type == "医疗物资" and box.first_batch)
        deadlines = _hard_deadlines(box)
        self.assertEqual({name for name, _ in deadlines}, {"医疗期望送达", "首批截止"})

    def test_baseline_schedule_is_fully_feasible(self):
        sorties, metrics, boxes = solve()
        self.assertTrue(metrics["feasible"], metrics["violations"])
        self.assertTrue(metrics["hard_deadlines_feasible"])
        self.assertTrue(metrics["resource_schedule_feasible"])
        self.assertEqual(metrics["hard_deadline_compliance_rate"], 1.0)
        self.assertEqual(metrics["all_due_box_count"], 80)
        self.assertGreaterEqual(metrics["all_expected_on_time_rate"], metrics["soft_on_time_rate"])
        self.assertEqual(metrics["assigned_box_count"], len(boxes))
        self.assertEqual(metrics["box_count"], 80)
        self.assertGreater(len({sortie.route[0] for sortie in sorties}), 1)
        self.assertTrue(all(sortie.return_s >= sortie.takeoff_s for sortie in sorties))
        candidates = metrics["tradeoff_candidates"]
        self.assertTrue(candidates)
        selected_key = (
            metrics["weighted_all_expected_tardiness"], metrics["makespan_s"],
            metrics["total_energy_kwh"], metrics["sortie_count"],
        )
        candidate_keys = [
            (item["weighted_all_expected_tardiness"], item["makespan_s"],
             item["total_energy_kwh"], item["sortie_count"])
            for item in candidates.values() if item["feasible"]
        ]
        self.assertEqual(selected_key, min(candidate_keys))
        labels = list(candidates)
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(any("不跨区" in label for label in labels))
        self.assertTrue(any("多点合并" in label for label in labels))

    def test_audit_replays_timeline_and_delivery_records(self):
        sorties, _, boxes = solve()
        drones, batteries = load_resources()
        evaluator = RouteEvaluator(0.2, 1.0)
        try:
            altered = copy.deepcopy(sorties)
            altered[0].return_s += 1
            result = _validate(altered, boxes, drones, batteries, evaluator)
            self.assertFalse(result["physics_and_timeline_feasible"])
            self.assertTrue(any("timeline replay mismatch" in issue for issue in result["violations"]))

            altered = copy.deepcopy(sorties)
            altered[0].deliveries.pop(altered[0].boxes[0].code)
            result = _validate(altered, boxes, drones, batteries, evaluator)
            self.assertFalse(result["physics_and_timeline_feasible"])
            self.assertTrue(any("delivery record coverage mismatch" in issue for issue in result["violations"]))
        finally:
            evaluator.close()
if __name__ == "__main__":
    unittest.main()
