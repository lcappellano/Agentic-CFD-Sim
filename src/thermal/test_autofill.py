"""Autofill rules on the analytic pipe: target margin, subcooling, plausibility stops, bounds, pump limit."""
import unittest

from src.thermal.autofill import choose_operating_point, explain, round_significant, smallest, hot, ATMOSPHERE_PA, PRESSURE_STEP_PA
from src.thermal.materials import material_basis
from src.thermal.prescreen import DEFAULTS, channel_model, estimate, prescreen, markdown
from src.thermal.saturation import saturation_pressure, saturation_temperature
from src.thermal.test_prescreen import pipe_geometry


class AutofillTests(unittest.TestCase):
    def setUp(self):
        self.basis = material_basis('copper', 'water', 283.15)
        self.rho = self.basis['fluid_properties']['density_kg_m3']
        self.operating = {'inlet_temperature_K': 283.15, 'temperature_limit_K': 473.15, 'heat_flux_W_m2': 1e6}
        self.model = channel_model(pipe_geometry(), DEFAULTS)

    def row(self, flow, operating=None):
        return estimate(flow, self.model, self.basis, operating or self.operating, DEFAULTS)

    def choose(self, operating=None, **kwargs):
        return choose_operating_point(pipe_geometry(), self.basis, operating or self.operating, **kwargs)

    def search(self, operating, predicate):
        return smallest(lambda f: predicate(self.row(f, operating)), 1e-5, 1e5)

    def test_rounding_to_two_significant_figures(self):
        self.assertAlmostEqual(round_significant(0.003377, 2), 0.0034)
        self.assertAlmostEqual(round_significant(0.0035, 2), 0.0035)
        self.assertEqual(round_significant(31.57, 2), 32)
        self.assertEqual(round_significant(31.57, 2, up=False), 31)
        self.assertEqual(round_significant(1.133, 2), 1.2)

    def test_flow_is_the_temperature_flow_when_the_wall_is_already_subcooled(self):
        operating = {**self.operating, 'temperature_limit_K': 350., 'heat_flux_W_m2': 1e5}
        choice = self.choose(operating)
        target = 283.15 + .75 * (350. - 283.15)
        needed = self.search(operating, lambda row: hot(row) <= target)
        self.assertAlmostEqual(choice['volume_flow_L_min'], round_significant(needed, 2))
        self.assertEqual(choice['outlet_absolute_pressure_Pa'], ATMOSPHERE_PA)
        self.assertFalse(any('Raised' in reason for reason in choice['reasons']))
        self.assertEqual(choice['stop'], [])

    def test_flow_is_raised_to_stay_subcooled_at_atmospheric_pressure(self):
        operating = {**self.operating, 'heat_flux_W_m2': 3e5}
        choice = self.choose(operating)
        target = 283.15 + .75 * (473.15 - 283.15)
        needed = self.search(operating, lambda row: hot(row) <= target)
        cool = self.search(operating, lambda row: row['wall_temperature_K']['spread'] <= saturation_temperature(ATMOSPHERE_PA) - 10)
        self.assertGreater(cool, needed)
        self.assertAlmostEqual(choice['volume_flow_L_min'], round_significant(cool, 2))
        self.assertLess(choice['estimate']['mean_speed_m_s'], 10)
        self.assertEqual(choice['outlet_absolute_pressure_Pa'], ATMOSPHERE_PA)
        self.assertAlmostEqual(choice['mass_flow_kg_s'], choice['volume_flow_L_min'] / 60000 * self.rho)
        self.assertTrue(any('75%' in reason for reason in choice['reasons']))
        self.assertTrue(any('below saturation at 1.01 bar' in reason for reason in choice['reasons']))
        self.assertEqual(choice['stop'], [])
        self.assertEqual(choice['warnings'], [])
        self.assertIn('Estimated operating point:', explain(choice))

    def test_pressure_makes_up_the_rest_once_the_plausible_velocity_is_reached(self):
        choice = self.choose(options={'plausible_velocity_m_s': 5.})  # subcooling at 1 atm would need about 6 m/s
        fast = self.search(self.operating, lambda row: row['mean_speed_m_s'] > 5)
        self.assertAlmostEqual(choice['volume_flow_L_min'], round_significant(fast, 2, up=False))
        self.assertLessEqual(choice['estimate']['mean_speed_m_s'], 5)
        needed = saturation_pressure(self.row(choice['volume_flow_L_min'])['wall_temperature_K']['spread'] + 10)
        pressure = choice['outlet_absolute_pressure_Pa']
        self.assertGreater(needed, ATMOSPHERE_PA)
        self.assertGreaterEqual(pressure, needed)
        self.assertLess(pressure - needed, PRESSURE_STEP_PA)
        self.assertAlmostEqual(pressure % PRESSURE_STEP_PA, 0)
        self.assertTrue(any('most flow within the plausible 5 m/s' in reason for reason in choice['reasons']))
        self.assertTrue(any('rounded up to 0.5 bar' in reason for reason in choice['reasons']))
        self.assertEqual(choice['stop'], [])

    def test_implausible_needs_stop_instead_of_being_capped(self):
        slow = self.choose(options={'plausible_velocity_m_s': 3.})  # the temperature target alone needs 3.5 m/s
        target = 283.15 + .75 * (473.15 - 283.15)
        needed = self.search(self.operating, lambda row: hot(row) <= target)
        self.assertAlmostEqual(slow['volume_flow_L_min'], round_significant(needed, 2))  # not lowered
        self.assertTrue(any('above the plausible 3 m/s' in reason and 'temperature target' in reason for reason in slow['stop']))
        pressure = self.choose(options={'plausible_velocity_m_s': 5., 'plausible_outlet_pressure_Pa': 1.2e5})
        self.assertGreater(pressure['outlet_absolute_pressure_Pa'], 1.2e5)  # not lowered
        self.assertTrue(any('above the plausible 1.20 bar' in reason for reason in pressure['stop']))
        drop = self.choose(options={'plausible_pressure_drop_Pa': 1e3})
        self.assertTrue(any('pressure drop' in reason for reason in drop['stop']))
        text = explain(drop)
        self.assertIn('operator input needed', text)
        self.assertIn('- STOP:', text)

    def test_review_upper_bounds_and_pump_limit_stop_instead_of_clamping(self):
        free = self.choose()
        self.assertEqual(free['stop'], [])
        flow, pressure = free['volume_flow_L_min'], free['outlet_absolute_pressure_Pa']
        upper = self.choose(handoff_requirements={'mass_flow_bounds_kg_s': [None, .5 * free['mass_flow_kg_s']]})
        self.assertEqual(upper['volume_flow_L_min'], flow)
        self.assertTrue(any('upper flow bound' in reason for reason in upper['stop']))
        tight = self.choose(handoff_requirements={'outlet_absolute_pressure_bounds_Pa': [None, .5 * pressure]})
        self.assertEqual(tight['outlet_absolute_pressure_Pa'], pressure)
        self.assertTrue(any('upper pressure bound' in reason for reason in tight['stop']))
        pump = self.choose({**self.operating, 'max_pump_pressure_rise_Pa': .5 * free['estimate']['pressure_drop_Pa']})
        self.assertEqual(pump['volume_flow_L_min'], flow)
        self.assertIs(pump['within_pump_limit'], False)
        self.assertTrue(any('pump limit' in reason for reason in pump['stop']))
        lower = self.choose(handoff_requirements={'mass_flow_bounds_kg_s': [2 * free['mass_flow_kg_s'], None]})
        self.assertAlmostEqual(lower['volume_flow_L_min'], 2 * flow)
        self.assertTrue(any('lower flow bound' in reason for reason in lower['reasons']))
        self.assertTrue(any("set by the review's lower flow bound" in reason for reason in lower['stop']))  # 12 m/s
        floor = self.choose(handoff_requirements={'outlet_absolute_pressure_bounds_Pa': [3e5, 5e5]})
        self.assertEqual(floor['outlet_absolute_pressure_Pa'], 3e5)
        self.assertEqual(floor['stop'], [])

    def test_fixed_values_are_kept_and_only_warned(self):
        choice = self.choose(fixed={'volume_flow_L_min': 5., 'outlet_absolute_pressure_Pa': ATMOSPHERE_PA})
        self.assertEqual(choice['volume_flow_L_min'], 5.)
        self.assertEqual(choice['outlet_absolute_pressure_Pa'], ATMOSPHERE_PA)
        self.assertEqual(sum('fixed' in reason for reason in choice['reasons']), 2)
        self.assertEqual(choice['stop'], [])
        self.assertTrue(any('below saturation' in warning for warning in choice['warnings']))

    def test_fixed_pressure_raises_the_flow_and_stops_when_that_is_implausible(self):
        cool = self.search(self.operating, lambda row: row['wall_temperature_K']['spread'] <= saturation_temperature(ATMOSPHERE_PA) - 10)
        choice = self.choose(fixed={'outlet_absolute_pressure_Pa': ATMOSPHERE_PA})
        self.assertAlmostEqual(choice['volume_flow_L_min'], round_significant(cool, 2))
        self.assertEqual(choice['stop'], [])
        strict = self.choose(fixed={'outlet_absolute_pressure_Pa': ATMOSPHERE_PA}, options={'plausible_velocity_m_s': 5.})
        self.assertAlmostEqual(strict['volume_flow_L_min'], round_significant(cool, 2))  # still what subcooling needs
        self.assertTrue(any('subcooling at 1.01 bar' in reason and 'above the plausible 5 m/s' in reason for reason in strict['stop']))

    def test_infeasible_target_stops(self):
        choice = self.choose({'inlet_temperature_K': 283.15, 'temperature_limit_K': 300., 'heat_flux_W_m2': 1e7})
        self.assertIsNone(choice['volume_flow_L_min'])
        self.assertIsNone(choice['outlet_absolute_pressure_Pa'])
        self.assertTrue(any('No flow meets the target' in reason for reason in choice['stop']))
        self.assertIn('No feasible operating point', explain(choice))

    def test_prescreen_centres_the_sweep_on_the_estimate(self):
        result = prescreen(pipe_geometry(), self.basis, self.operating, {'points': 5})
        choice = result['autofill']
        flows = [row['flow_L_min'] for row in result['rows']]
        self.assertAlmostEqual(flows[0], choice['volume_flow_L_min'] / 10)
        self.assertAlmostEqual(flows[-1], choice['volume_flow_L_min'] * 10)
        self.assertIn(choice['outlet_absolute_pressure_Pa'], result['pressures_Pa'])
        self.assertIn('Estimated operating point', markdown(result, self.operating))
        self.assertFalse(any('No flow estimate' in warning for warning in result['warnings']))


if __name__ == '__main__':
    unittest.main()
