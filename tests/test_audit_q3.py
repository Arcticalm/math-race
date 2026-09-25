"""Regression checks for the submission's exact-pixel communication audit."""
import unittest

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from final_code.problem1.solver import Node
from final_code.problem3.audit import audit_relay_resources, rebuild_relay_mission
from final_code.problem3.physics import (
    LinkEvaluator, certify_moving_link, estimate_relay_mission, load_relay_parameters,
    sampled_flight_leg, load_link_parameters,
)


class ExactCommunicationAuditTests(unittest.TestCase):
    def raster_evaluator(self, raster):
        memory = MemoryFile()
        dataset = memory.open(driver="GTiff", height=6, width=6, count=1,
                              dtype="float32", crs="EPSG:4326",
                              transform=from_origin(0, 0.0006, 0.0001, 0.0001),
                              nodata=-32767)
        dataset.write(raster, 1)
        evaluator = LinkEvaluator()
        evaluator.dem.close()
        evaluator.dem, evaluator.dem_values = dataset, raster
        self.addCleanup(memory.close)
        self.addCleanup(evaluator.close)
        return evaluator

    def test_corner_touch_ridge_changes_both_los_and_flight_clearance(self):
        terrain = np.zeros((6, 6), dtype=np.float32)
        terrain[1, 2] = 150
        evaluator = self.raster_evaluator(terrain)
        first = Node("A", 0.00005, 0.00055, 0)
        last = Node("B", 0.00045, 0.00015, 0)
        for start, end in ((first, last), (last, first)):
            self.assertTrue(evaluator.evaluate(start, 100, end, 100, 200).obstruction)
            self.assertEqual(sampled_flight_leg(evaluator, start, end)[0], 150)
        evaluator.dem_values[1, 2] = -32767
        self.assertFalse(evaluator.evaluate(first, 100, last, 100, 200).available)
        with self.assertRaisesRegex(ValueError, "NoData"):
            sampled_flight_leg(evaluator, first, last)

    def test_continuous_certificate_covers_in_between_los_positions(self):
        terrain = np.zeros((6, 6), dtype=np.float32)
        terrain[2, 2] = 150
        evaluator = self.raster_evaluator(terrain)
        first = Node("A", 0.00005, 0.00045, 0)
        last = Node("A", 0.00005, 0.00035, 0)
        fixed = Node("G01", 0.00045, 0.00005, 0)
        self.assertFalse(certify_moving_link(evaluator, first, 100, last, 100,
                                             fixed, 100, 83))
        self.assertTrue(certify_moving_link(evaluator, first, 200, last, 200,
                                            fixed, 200, 83))
        for altitude in (100, 150, 200):
            for threshold in (75, 83, 90):
                if certify_moving_link(evaluator, first, altitude, last, altitude,
                                       fixed, altitude, threshold):
                    for t in np.linspace(0, 1, 51):
                        point = Node("A", first.longitude,
                                     first.latitude + t * (last.latitude - first.latitude), 0)
                        self.assertTrue(evaluator.evaluate(point, altitude, fixed,
                                                           altitude, threshold).available)

    def mission(self):
        evaluator = LinkEvaluator()
        self.addCleanup(evaluator.close)
        longitude, latitude = 109.28027778, 23.03333333
        row, col = evaluator.dem.index(longitude, latitude)
        draft = dict(relay_sortie="R-test", longitude=longitude, latitude=latitude,
                     hover_altitude_m=float(evaluator.dem_values[row, col]) + 300,
                     service_start_s=1000.0, service_end_s=1300.0,
                     relay_drone="R01", energy_component="RE-01", covered_sorties="T1")
        return rebuild_relay_mission(draft, evaluator)

    def test_relay_audit_rejects_false_agl_ground_and_charge_fields(self):
        mission = self.mission()
        self.assertTrue(audit_relay_resources([mission])["feasible"])
        for field, delta in (("ground_dsm_m", 1), ("agl_m", -1),
                             ("charge_complete_s", -1), ("takeoff_s", 1)):
            result = audit_relay_resources([{**mission, field: mission[field] + delta}])
            self.assertFalse(result["feasible"], field)
            self.assertTrue(any(row.get("field") == field for row in result["conflicts"]))
        excessive = {**mission, "hover_altitude_m": mission["hover_altitude_m"] + 1}
        self.assertFalse(audit_relay_resources([excessive])["feasible"])
        self.assertFalse(audit_relay_resources([mission, mission])["feasible"])

    def test_setup_hover_energy_and_high_altitude_climb_are_included(self):
        params = load_relay_parameters()
        estimate = estimate_relay_mission(600, 0, 100, 400, 0, 100, 100, params)
        expected_climb = params.takeoff_mass_kg * 9.80665 * 300 / (3600000 * params.climb_efficiency)
        expected_hover = (params.hover_power_kw + params.communication_power_kw) * (600 + params.link_setup_s) / 3600
        self.assertAlmostEqual(estimate.energy_kwh, expected_climb + expected_hover)
        self.assertAlmostEqual(estimate.outbound_flight_s, 300 / params.climb_speed_mps)
        self.assertAlmostEqual(estimate.return_flight_s, 300 / params.descent_speed_mps)
        self.assertEqual(load_link_parameters().gateway_agl_m, 20)


if __name__ == "__main__":
    unittest.main()
