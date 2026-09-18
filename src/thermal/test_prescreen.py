"""Prescreen correlations against reference values and the analytic pipe."""
import math
import unittest

from src.thermal.materials import material_basis
from src.thermal.prescreen import friction_factor, nusselt, channel_model, estimate, prescreen, markdown, DEFAULTS


def pipe_geometry(radius=.004, length=.06):
    volume = math.pi * radius ** 2 * length
    return {'regions': {'fluid': {'volume_m3': volume}}, 'heated_area_m2': .0024, 'heated_to_passage_distance_m': .006,
            'boundary_map': {'interface': {'area_m2': 2 * math.pi * radius * length},
                             'inlet': {'area_m2': math.pi * radius ** 2, 'centroids_m': [[0, .02, .01]]},
                             'outlet': {'area_m2': math.pi * radius ** 2, 'centroids_m': [[length, .02, .01]]}}}


class CorrelationTests(unittest.TestCase):
    def test_gnielinski_reference_point(self):
        factor, regime = friction_factor(1e4)
        self.assertEqual(regime, 'turbulent')
        self.assertAlmostEqual(factor, .0315, places=3)
        self.assertTrue(29 < nusselt(1e4, .7, factor) < 31)
        self.assertEqual(friction_factor(1000), (.064, 'laminar'))
        self.assertEqual(nusselt(1000, 7, .064), 4.36)

    def test_equivalent_duct_is_exact_for_a_straight_pipe(self):
        options = {**DEFAULTS, 'minor_loss_coefficient': 0}
        model = channel_model(pipe_geometry(), options)
        self.assertAlmostEqual(model['hydraulic_diameter_m'], .008)
        self.assertAlmostEqual(model['flow_path_length_m'], .06)
        self.assertEqual(model['solid_thickness_m'], .006)
        basis = material_basis('copper', 'water', 300)
        operating = {'inlet_temperature_K': 300, 'temperature_limit_K': 500, 'heat_flux_W_m2': 1e5}
        row = estimate(30, model, basis, operating, options)
        rho = basis['fluid_properties']['density_kg_m3']
        self.assertAlmostEqual(row['mean_speed_m_s'], 30 / 60000 / (math.pi * .004 ** 2))
        self.assertAlmostEqual(row['mass_flow_kg_s'], rho * 30 / 60000)
        self.assertAlmostEqual(row['outlet_temperature_K'] - 300, 240 / (row['mass_flow_kg_s'] * basis['fluid_properties']['cp_J_kg_K']))
        self.assertGreaterEqual(row['heated_temperature_K']['peak'], row['heated_temperature_K']['spread'])
        self.assertAlmostEqual(row['wall_flux_W_m2']['peak'], 240 / (2 * math.pi * .004 * .06))
        self.assertAlmostEqual(row['conduction_rise_K'], 1e5 * .006 / 394)
        self.assertEqual(row['minor_pressure_drop_Pa'], 0)

    def test_sweep_matrix_recommendation_and_table(self):
        basis = material_basis('copper', 'water', 283.15)
        operating = {'inlet_temperature_K': 283.15, 'temperature_limit_K': 473.15, 'heat_flux_W_m2': 1e6, 'max_pump_pressure_rise_Pa': 8e5}
        result = prescreen(pipe_geometry(), basis, operating, {'flow_range_L_min': [1, 40], 'points': 5, 'outlet_pressures_bar': [1, 4]})
        self.assertEqual(len(result['rows']), 5)
        self.assertEqual([len(cells) for cells in result['matrix']], [2] * 5)
        drops = [r['pressure_drop_Pa'] for r in result['rows']]
        self.assertEqual(drops, sorted(drops))
        walls = [r['wall_temperature_K']['spread'] for r in result['rows']]
        self.assertEqual(walls, sorted(walls, reverse=True))
        rec = result['recommendation']
        self.assertIsNotNone(rec['flow_L_min'])
        self.assertIn(rec['outlet_absolute_pressure_Pa'], result['pressures_Pa'])
        text = markdown(result, operating)
        self.assertIn('Suggested CFD starting point', text)
        self.assertIn('| flow L/min |', text)

    def test_impossible_sweep_reports_no_point(self):
        basis = material_basis('copper', 'water', 283.15)
        operating = {'inlet_temperature_K': 283.15, 'temperature_limit_K': 300, 'heat_flux_W_m2': 1e7}
        result = prescreen(pipe_geometry(), basis, operating, {'flow_range_L_min': [1, 2], 'points': 2})
        self.assertIsNone(result['recommendation']['flow_L_min'])
        self.assertIn('default list', result['pressure_source'])


if __name__ == '__main__':
    unittest.main()
