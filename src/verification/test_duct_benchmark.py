"""Reduction arithmetic of the smooth-duct benchmark on synthetic profiles."""
import math
import unittest

import numpy as np

from src.thermal.prescreen import friction_factor, nusselt
from src.verification.duct_benchmark import developed_friction, nusselt_from_bins


class DuctBenchmarkTests(unittest.TestCase):
    def test_friction_recovered_from_a_linear_developed_profile(self):
        rho, u, d, f_true = 998.0, 13.0, 0.002, 0.0245
        gradient = f_true / d * 0.5 * rho * u ** 2
        x = np.linspace(0, 0.1, 41)
        p = 9e5 - gradient * x + 3e3 * np.exp(-x / 0.005)  # entry effect decays before the window
        f, grad, (lo, hi) = developed_friction(x, p, rho, u, d)
        self.assertAlmostEqual(f, f_true, places=5)
        self.assertAlmostEqual(grad / gradient, 1.0, places=4)
        self.assertAlmostEqual(lo, 0.04)
        self.assertAlmostEqual(hi, 0.08)
        with self.assertRaises(ValueError):
            developed_friction(x[:2], p[:2], rho, u, d)

    def test_local_nusselt_from_wall_and_bulk_bins(self):
        d, k, h = 0.002, 0.6, 50000.0
        edges = np.linspace(0, 0.1, 11)
        wall_x = np.repeat(0.5 * (edges[:-1] + edges[1:]), 3) + np.tile([-0.002, 0, 0.002], 10)
        bulk_x = 0.5 * (edges[:-1] + edges[1:])
        tb = 293 + 30 * bulk_x
        q = 1.2e6
        tw = np.repeat(tb, 3) + q / h
        rows = nusselt_from_bins(wall_x, np.full(30, q), tw, np.full(30, 1e-6), bulk_x, tb, d, k, edges)
        self.assertEqual(len(rows), 10)
        for row in rows:
            self.assertAlmostEqual(row['nusselt'], h * d / k, places=6)
            self.assertAlmostEqual(row['wall_flux_W_m2'], q)

    def test_reference_values_are_the_prescreen_correlations(self):
        f, regime = friction_factor(26000)
        self.assertEqual(regime, 'turbulent')
        self.assertAlmostEqual(f, (0.79 * math.log(26000) - 1.64) ** -2)
        self.assertGreater(nusselt(26000, 7.0, f), 150)
        self.assertLess(nusselt(26000, 7.0, f), 220)


if __name__ == '__main__':
    unittest.main()
