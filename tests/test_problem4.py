import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.problem4.solver import _peak, atomic_units, evaluate_partition, partitions, q3_gate, run


class Problem4Tests(unittest.TestCase):
    def test_peak_uses_half_open_intervals(self):
        self.assertEqual(_peak([(0, 10), (10, 20)]), 1)
        self.assertEqual(_peak([(0, 10), (9, 20)]), 2)

    def test_atomic_units_close_multisite_sorties(self):
        transport = [
            {"架次编号": "Q2-001", "访问服务区顺序": "S001,S002"},
            {"架次编号": "Q2-002", "访问服务区顺序": "S002,S003"},
        ]
        units = atomic_units(transport, [])
        self.assertIn(frozenset({"S001", "S002", "S003"}), units)
        self.assertEqual(sum(map(len, units)), 15)

    def test_q3_gate_rejects_missing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = q3_gate(Path(directory))
        self.assertFalse(gate["ready"])

    def test_partition_generator_honors_limit_without_materializing(self):
        units = [frozenset({f"S{i:03d}"}) for i in range(1, 7)]
        with self.assertRaises(RuntimeError):
            list(partitions(units, 3, max_candidates=2))

    def test_relay_alias_maps_tasks_and_unknown_sorties_fail(self):
        transport = [{"架次编号": f"T{i}", "访问服务区顺序": f"S{i:03d}"} for i in range(1, 16)]
        relay = [{"relay_sortie": "R1", "保障运输架次": "T1,T2"}]
        groups = [frozenset({f"S{i:03d}" for i in range(1, 3)}),
                  frozenset({f"S{i:03d}" for i in range(3, 16)})]
        inventory = {key: 20 for key in (
            "A_airframe", "B_airframe", "C_airframe", "A_battery", "B_battery",
            "C_battery", "relay_airframe", "relay_energy")}
        with self.assertRaises(ValueError):
            evaluate_partition(groups, transport, [{"relay_sortie": "R1", "保障运输架次": "missing"}], inventory)

    def test_ready_q3_generates_template_and_audit_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "q3", root / "q4"
            source.mkdir()
            headers = ["架次编号", "无人机编号", "机型编号", "电池编号", "准备开始时刻（s）", "起飞时刻（s）", "返回O01时刻（s）", "访问服务区顺序", "架次能耗（kWh）", "返航SOC（%）", "逐箱交付数"]
            rows = [
                ["T1", "U1", "A", "A1", 0, 10, 100, ",".join(f"S{i:03d}" for i in range(1, 6)), 1, 80, 5],
                ["T2", "U2", "A", "A2", 200, 210, 300, ",".join(f"S{i:03d}" for i in range(6, 11)), 1, 80, 5],
                ["T3", "U3", "A", "A3", 400, 410, 500, ",".join(f"S{i:03d}" for i in range(11, 16)), 1, 80, 5],
            ]
            with (source / "transport_inherited_audit.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream); writer.writerow(headers); writer.writerows(rows)
            for name, fields, data in (
                ("relay_schedule.csv", ["relay_sortie", "covered_sorties"], []),
                ("relay_resource_audit.csv", ["中继架次编号"], []),
                ("communication_audit.csv", ["运输架次编号", "保障方式"], [["T1", "直连"]]),
            ):
                with (source / name).open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream); writer.writerow(fields); writer.writerows(data)
            with patch("src.problem4.solver.q3_gate", return_value={"ready": True}), \
                 patch("src.problem4.solver.load_inventory", return_value={
                     "A_airframe": 4, "B_airframe": 2, "C_airframe": 2,
                     "A_battery": 6, "B_battery": 4, "C_battery": 4,
                     "relay_airframe": 2, "relay_energy": 6,
                 }):
                result = run(source, output)
            self.assertTrue(result["solutions"]["3"]["feasible"])
            self.assertTrue((output / "problem4_configuration.csv").exists())
            self.assertTrue((output / "inventory_comparison.csv").exists())
            with (output / "problem4_configuration.csv").open(encoding="utf-8-sig") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 5)


if __name__ == "__main__":
    unittest.main()
