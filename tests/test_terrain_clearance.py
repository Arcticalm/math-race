import unittest
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from src.problem1.solver import DEM_PATH, Node, load_nodes, sample_leg
from src.problem23.terrain_audit import audit_clearance, intersected_ground


class TerrainClearanceTests(unittest.TestCase):
    def check_raster(self, heights, start_pixel, end_pixel, expected=None, nodata=None):
        transform = from_origin(0, 3, 1, 1)
        def node(code, pixel):
            x, y = transform * pixel
            return Node(code, x, y, 0)
        start, end = node('start', start_pixel), node('end', end_pixel)
        with MemoryFile() as memory:
            with memory.open(driver='GTiff', width=3, height=3, count=1,
                             dtype='float64', transform=transform, crs='EPSG:4326',
                             nodata=nodata) as dem:
                dem.write(np.asarray(heights, dtype=float), 1)
                for a, b in [(start, end), (end, start)]:
                    if expected is None:
                        with self.assertRaises(ValueError):
                            sample_leg(dem, a, b)
                        with self.assertRaises(ValueError):
                            intersected_ground(dem, a, b)
                    else:
                        self.assertEqual(sample_leg(dem, a, b)[0], expected)
                        self.assertEqual(intersected_ground(dem, a, b)[0], expected)

    def test_short_cell_intersection_peak(self):
        heights = np.zeros((3, 3))
        heights[0, 1] = 400
        self.check_raster(heights, (.2, .19), (2.8, 2.81), 400)

    def test_corner_contact_peak(self):
        heights = np.zeros((3, 3))
        heights[0, 1] = 500
        self.check_raster(heights, (.5, .5), (2.5, 2.5), 500)

    def test_edge_contact_peak(self):
        heights = np.zeros((3, 3))
        heights[0, 1] = 600
        self.check_raster(heights, (.2, 1), (2.8, 1), 600)

    def test_nodata_on_route_rejected(self):
        heights = np.zeros((3, 3))
        heights[1, 1] = -9999
        self.check_raster(heights, (.5, .5), (2.5, 2.5), nodata=-9999)

    def test_nonfinite_on_route_rejected(self):
        heights = np.zeros((3, 3))
        heights[1, 1] = np.nan
        self.check_raster(heights, (.5, .5), (2.5, 2.5))

    def test_outside_extent_rejected(self):
        self.check_raster(np.zeros((3, 3)), (-.1, .5), (2.5, 2.5))

    def test_audit_rejects_original_s007_altitude(self):
        base, sites = load_nodes()
        leg = {"from": "O01", "to": "S007", "cruise_altitude_m": 501.8304748535156}
        sortie = SimpleNamespace(code="regression", legs=[leg])
        with rasterio.open(DEM_PATH) as dem:
            evaluator = SimpleNamespace(base=base, sites=sites, dem=dem)
            report = audit_clearance([sortie], evaluator)
            self.assertFalse(report["feasible"])
            self.assertAlmostEqual(report["minimum_clearance_m"], 39.8572998046875)
            leg["cruise_altitude_m"] = 511.9731750488281
            self.assertTrue(audit_clearance([sortie], evaluator)["feasible"])

    def test_known_s007_peak(self):
        base, sites = load_nodes()
        with rasterio.open(DEM_PATH) as dem:
            maximum, _ = sample_leg(dem, base, sites['S007'])
            independent, _ = intersected_ground(dem, base, sites['S007'])
        self.assertAlmostEqual(maximum, 461.9731750488281)
        self.assertEqual(maximum, independent)


if __name__ == '__main__':
    unittest.main()
