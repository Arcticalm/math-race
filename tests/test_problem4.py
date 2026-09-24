import tempfile
import unittest
from pathlib import Path

from src.problem4.solver import _peak, atomic_units, q3_gate


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


if __name__ == "__main__":
    unittest.main()
