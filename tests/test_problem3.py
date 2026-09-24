import unittest
from pathlib import Path

import numpy as np
import json
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from src.problem1.solver import Node
from src.problem2.solver import solve as solve_problem2
from src.problem3.physics import (
    LinkEvaluator,
    estimate_relay_mission,
    link_limits,
    load_link_parameters,
    load_relay_parameters,
)
from src.problem3.solver import (
    build_trajectory,
    coordinate_transport_starts,
    select_relay_schedule,
)


class CommunicationPhysicsTests(unittest.TestCase):
    def test_workbook_link_limits(self):
        limits = link_limits(load_link_parameters())
        self.assertAlmostEqual(limits["transport_gateway_db"], 122.0)
        self.assertAlmostEqual(limits["transport_relay_db"], 116.0)
        self.assertAlmostEqual(limits["relay_gateway_db"], 126.0)

    def test_relay_parameters_and_energy_model(self):
        params = load_relay_parameters()
        self.assertEqual(params.battery_count, 6)
        self.assertEqual(params.full_charge_s, 1800)
        estimate = estimate_relay_mission(
            service_s=600, outbound_distance_m=0, outbound_max_dsm_m=100,
            hover_altitude_m=150, return_distance_m=0, return_max_dsm_m=100,
            base_altitude_m=150, parameters=params,
        )
        expected_hover_energy = 1.10 * (params.link_setup_s + 600) / 3600
        self.assertAlmostEqual(estimate.energy_kwh, expected_hover_energy)
        self.assertAlmostEqual(estimate.return_time_s,
                               params.preparation_s + estimate.outbound_flight_s
                               + params.link_setup_s + 600 + estimate.return_flight_s)

    def test_relay_resource_assignment_backtracks_without_conflicts(self):
        def candidate(gap_ids, start, end, prepare, return_time, energy=0.5):
            return {
                "covered_gap_ids": gap_ids, "preparation_start_s": prepare,
                "service_start_s": start, "service_end_s": end,
                "return_o01_s": return_time, "return_soc_percent": 80.0,
                "energy_kwh": energy, "longitude": 109.2, "latitude": 23.0,
                "hover_altitude_m": 200.0,
            }

        result = select_relay_schedule([
            {"group": 1, "gap_start_s": 1500, "gap_start_by_id": {"1": 1500, "2": 2600},
             "candidates": [candidate([1], 1500, 1700, 1000, 2500, 0.1),
                            candidate([1], 1500, 1700, 1000, 1700, 0.2),
                            candidate([2], 2600, 2800, 2000, 3000)]},
        ], gap_count=2)
        self.assertTrue(result["feasible_cover"])
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual({tuple(item["covered_gap_ids"]) for item in result["selected"]}, {(1,), (2,)})
        self.assertTrue(all(item["relay_drone"] in {"R01", "R02"} for item in result["selected"]))

        missing = select_relay_schedule([{"group": 1, "gap_start_s": 1500, "gap_start_by_id": {"1": 1500},
                                          "candidates": [candidate([1], 1500, 2000, 1000, 2000)]}], gap_count=2)
        self.assertFalse(missing["feasible_cover"])
        self.assertEqual(missing["uncovered_gap_ids"], [2])

    def _evaluator(self, raster):
        memory = MemoryFile()
        dataset = memory.open(
            driver="GTiff", height=3, width=3, count=1, dtype=raster.dtype,
            crs="EPSG:4326", transform=from_origin(0, 0.003, 0.001, 0.001), nodata=-32767,
        )
        dataset.write(raster, 1)
        evaluator = LinkEvaluator()
        evaluator.dem.close()
        evaluator.dem = dataset
        evaluator._memory_file = memory
        return evaluator

    def test_coincident_endpoints_are_rejected_without_log_zero(self):
        evaluator = LinkEvaluator()
        try:
            node = Node("A", 109.2, 23.0, 100)
            result = evaluator.evaluate(node, 100, node, 100, 122)
            self.assertFalse(result.available)
            self.assertEqual(result.reason, "coincident 3D endpoints")
        finally:
            evaluator.close()

    def test_dem_obstruction_and_nodata_are_conservative(self):
        first = Node("A", 0.0005, 0.0015, 100)
        second = Node("B", 0.0025, 0.0015, 100)
        clear = self._evaluator(np.zeros((3, 3), dtype=np.float32))
        try:
            result = clear.evaluate(first, 100, second, 100, 200)
            self.assertIs(result.obstruction, False)
        finally:
            clear.close()
            clear._memory_file.close()

        ridge = np.zeros((3, 3), dtype=np.float32)
        ridge[1, 1] = 150
        blocked = self._evaluator(ridge)
        try:
            blocked.dem_values[1, 1] = 150
            result = blocked.evaluate(first, 100, second, 100, 200)
            self.assertIs(result.obstruction, True)
            ridge[1, 1] = -32767
            blocked.dem.write(ridge, 1)
            blocked.dem_values[1, 1] = -32767
            result = blocked.evaluate(first, 100, second, 100, 200)
            self.assertFalse(result.available)
            self.assertEqual(result.reason, "DEM NoData or outside extent")
        finally:
            blocked.close()
            blocked._memory_file.close()

    def test_reconstructed_track_matches_problem2_sortie_times(self):
        sorties, _, _ = solve_problem2()
        phases = build_trajectory(sorties)
        by_sortie = {}
        for phase in phases:
            by_sortie.setdefault(phase.sortie, []).append(phase)
        self.assertEqual(set(by_sortie), {sortie.code for sortie in sorties})
        for sortie in sorties:
            track = sorted(by_sortie[sortie.code], key=lambda item: item.start_s)
            self.assertAlmostEqual(track[0].start_s, sortie.takeoff_s)
            self.assertAlmostEqual(track[-1].end_s, sortie.return_s)
            for previous, current in zip(track, track[1:]):
                self.assertAlmostEqual(previous.end_s, current.start_s)

    def test_output_contract_does_not_claim_feasibility_when_gaps_remain(self):
        from tempfile import TemporaryDirectory

        from src.problem3.solver import run

        with TemporaryDirectory() as temporary_directory:
            result = run(Path(temporary_directory), sample_step_s=300, relay_candidate_step_s=300)
            self.assertFalse(result["relay_schedule"]["feasible_cover"])
            self.assertIn("not a feasible Q3 solution", result["status"])
            saved = json.loads((Path(temporary_directory) / "screening.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["continuity_certified"])


if __name__ == "__main__":
    unittest.main()
