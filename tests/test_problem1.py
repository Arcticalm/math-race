import unittest

from src.problem1.solver import (
    leg_flight,
    load_aircraft,
    load_boxes,
    load_nodes,
)


class ProblemOneInputTests(unittest.TestCase):
    def test_workbooks_have_expected_scope(self):
        aircraft = load_aircraft()
        base, sites = load_nodes()
        boxes = load_boxes()
        self.assertEqual(set(aircraft), {"A", "B", "C"})
        self.assertEqual(base.code, "O01")
        self.assertEqual(len(sites), 15)
        self.assertEqual(sum(map(len, boxes.values())), 80)


class ProblemOnePhysicsTests(unittest.TestCase):
    def test_flight_time_and_payload_adjusted_range(self):
        aircraft = load_aircraft()["A"]
        time_s, energy_kwh, range_m = leg_flight(
            aircraft, aircraft.usable_energy_kwh / aircraft.empty_range_m,
            distance_m=1000,
            cruise_altitude_m=300,
            start_altitude_m=100,
            end_altitude_m=150,
            payload_kg=0,
        )
        expected_time = 200 / aircraft.climb_speed_mps + 1000 / aircraft.cruise_speed_mps + 150 / aircraft.descent_speed_mps
        self.assertAlmostEqual(time_s, expected_time)
        self.assertGreater(energy_kwh, 0)
        self.assertAlmostEqual(range_m, aircraft.empty_range_m)

    def test_return_climb_uses_empty_vehicle_mass_override(self):
        aircraft = load_aircraft()["A"]
        _, empty_return_energy, _ = leg_flight(
            aircraft, 0, 0, 300, 100, 100, 0, aircraft.empty_mass_kg
        )
        _, loaded_energy, _ = leg_flight(
            aircraft, 0, 0, 300, 100, 100, 25
        )
        self.assertLess(empty_return_energy, loaded_energy)


if __name__ == "__main__":
    unittest.main()
