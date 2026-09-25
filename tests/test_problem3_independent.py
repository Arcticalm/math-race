import unittest

from src.problem3.independent import _select_transport_candidate


class IndependentProblem3Tests(unittest.TestCase):
    def test_transport_seed_prefers_fastest_rebuilt_schedule(self):
        candidates = [
            {"labels": ["fastest"], "metrics": {
                "sortie_count": 31, "weighted_all_expected_tardiness": 100,
                "makespan_s": 80, "total_energy_kwh": 2,
            }},
            {"labels": ["few sorties"], "metrics": {
                "sortie_count": 25, "weighted_all_expected_tardiness": 1,
                "makespan_s": 100, "total_energy_kwh": 1,
            }},
            {"labels": ["same makespan, lower lateness"], "metrics": {
                "sortie_count": 29, "weighted_all_expected_tardiness": 50,
                "makespan_s": 80, "total_energy_kwh": 1,
            }},
        ]
        self.assertEqual(_select_transport_candidate(candidates)["labels"],
                         ["same makespan, lower lateness"])


if __name__ == "__main__":
    unittest.main()
