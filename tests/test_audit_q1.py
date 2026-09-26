"""Regressions for the final question-one statement audit."""

import itertools
import math
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from final_code.problem1 import solver


class QuestionOneAuditTests(unittest.TestCase):
    def setUp(self):
        self.aircraft = solver.Aircraft(
            "A", "test", 1, 10, 1, 10, 1000, 800, 10, .2,
            1, 1, 1, 1, 2, 2, .72, 0,
        )
        self.base = solver.Node("O01", 0, 0, 0)
        self.sites = {
            "S001": solver.Node("S001", .001, 0, 0),
            "S002": solver.Node("S002", .002, 0, 0),
        }
        self.boxes = {
            site: [solver.Box(f"B{i}", site, "water", 2, .01)]
            for i, site in enumerate(self.sites, 1)
        }

    def small_run(self, reserves=None, energy_scales=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(solver, "load_aircraft", return_value={"A": self.aircraft}))
            stack.enter_context(patch.object(solver, "load_nodes", return_value=(self.base, self.sites)))
            stack.enter_context(patch.object(solver, "load_boxes", return_value=self.boxes))
            stack.enter_context(patch.object(solver.rasterio, "open"))
            stack.enter_context(patch.object(solver, "route_max_elevation", return_value=(0, 111)))
            return solver.run(reserves, energy_scales)

    def test_default_run_includes_reserve_and_energy_sensitivity(self):
        result = self.small_run()
        runs = result["runs"]
        self.assertEqual((runs[0]["reserve_fraction"], runs[0]["horizontal_energy_scale"]), (.2, 1.0))
        self.assertTrue(set(solver.DEFAULT_RESERVE_SENSITIVITY).issubset(
            {item["reserve_fraction"] for item in runs}))
        self.assertTrue(set(solver.DEFAULT_ENERGY_SENSITIVITY).issubset(
            {item["horizontal_energy_scale"] for item in runs}))
        payloads = [next(row["max_safe_payload_kg"] for row in item["safe_payloads"]
                         if row["site"] == "S002")
                    for item in sorted(runs, key=lambda item: item["reserve_fraction"])
                    if item["horizontal_energy_scale"] == 1.0]
        self.assertTrue(all(a >= b for a, b in zip(payloads, payloads[1:])))

    def test_infeasible_sensitivity_records_every_affected_site_and_plots(self):
        result = self.small_run([1.0], [])
        infeasible = result["runs"][1]
        self.assertFalse(infeasible["complete_delivery_feasible"])
        self.assertEqual(infeasible["infeasible_sites"], ["S001", "S002"])
        self.assertEqual(infeasible["partitions"], {})
        self.assertIsNone(infeasible["summary"]["flight_count"])
        self.assertTrue(all(not row["empty_round_trip_feasible"] for row in infeasible["safe_payloads"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reserve.png"
            solver._configure_plot_fonts()
            solver._plot_sensitivity(result["runs"], path)
            self.assertGreater(path.stat().st_size, 0)

    def test_empty_energy_export_uses_zero_payload(self):
        result = self.small_run([], [])
        row = result["runs"][0]["safe_payloads"][0]
        empty = solver.flight_for_payload(
            self.aircraft, .01, self.base, self.sites["S001"], 0, 0,
        )
        self.assertAlmostEqual(row["empty_round_trip_energy_kwh"], empty.energy_kwh)
        self.assertGreater(row["max_payload_round_trip_energy_kwh"], empty.energy_kwh)

    def test_sensitivity_rejects_invalid_parameter_domains(self):
        for reserve in (-.01, 1.01, math.nan, math.inf):
            with self.subTest(reserve=reserve), self.assertRaises(ValueError):
                self.small_run([reserve], [])
        for scale in (0, -1, math.nan, math.inf):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                self.small_run([], [scale])

    def test_safe_payload_uses_loaded_outbound_and_empty_return(self):
        site = solver.Node("far", .0033, 0, 0)
        payload, flight = solver.max_safe_payload(self.aircraft, .01, self.base, site, 0)
        self.assertGreater(payload, 0)
        self.assertLess(payload, self.aircraft.max_payload_kg)
        self.assertAlmostEqual(flight.energy_kwh, 8)
        heavier = solver.flight_for_payload(self.aircraft, .01, self.base, site, 0, payload + .01)
        self.assertGreater(heavier.energy_kwh, 8)
        empty = solver.flight_for_payload(self.aircraft, .01, self.base, site, 0, 0)
        self.assertAlmostEqual(flight.return_energy_kwh, empty.return_energy_kwh)

    def test_exact_partition_matches_exhaustive_complete_solutions(self):
        boxes = [solver.Box(code, "S001", "water", 1, .01) for code in "ABC"]

        def candidate(codes, energy, duration):
            return solver.Candidate("S001", "A", tuple(codes), len(codes), .01 * len(codes),
                                    energy, energy, 0, duration, duration, 0, duration,
                                    1000, 1000, 1, 90, True)

        candidates = [candidate("ABC", 8, 6), candidate("AB", 1, 2),
                      candidate("BC", 1, 2), candidate("A", .3, 1),
                      candidate("B", .3, 1), candidate("C", 1, 1)]
        complete = []
        for count in range(1, len(candidates) + 1):
            for combination in itertools.combinations(candidates, count):
                assigned = [box for item in combination for box in item.boxes]
                if sorted(assigned) == list("ABC"):
                    complete.append(combination)
        for order in ((0, 1, 2), (1, 0, 2), (2, 0, 1)):
            def score(solution):
                values = (len(solution), sum(item.energy_kwh for item in solution),
                          sum(item.work_time_s for item in solution))
                return tuple(values[index] for index in order)
            chosen = solver.solve_set_partition(boxes, candidates, order)
            self.assertEqual(score(chosen), min(map(score, complete)))

    def test_dem_corner_contacts_are_included(self):
        transform = from_origin(0, 3, 1, 1)
        heights = np.zeros((3, 3))
        heights[0, 1] = 500
        start = solver.Node("start", *(transform * (.5, .5)), 0)
        end = solver.Node("end", *(transform * (2.5, 2.5)), 0)
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=3, height=3, count=1,
                             dtype="float64", transform=transform, crs="EPSG:4326") as dem:
                dem.write(heights, 1)
                self.assertEqual(solver.sample_leg(dem, start, end)[0], 500)
                self.assertEqual(solver.sample_leg(dem, end, start)[0], 500)


if __name__ == "__main__":
    unittest.main()
