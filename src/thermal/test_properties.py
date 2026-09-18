"""Reference-value, material-lookup and unit-conversion checks."""
import unittest

from src.thermal.liquid_water import properties
from src.thermal.materials import material_basis, solid_name, fluid_name
from src.thermal.operating_screen import screen
from src.thermal.saturation import saturation_pressure, saturation_temperature


class PropertiesTests(unittest.TestCase):
    def test_iapws_table8(self):
        p = properties(298.15)
        self.assertAlmostEqual(p['density_kg_m3'], 997.047013, places=5)
        self.assertAlmostEqual(p['cp_J_kg_K'], 4181.44618, places=4)

    def test_range_guard(self):
        for t in (200, 400, float('nan')):
            with self.assertRaises(ValueError):
                properties(t)

    def test_saturation_reference_points(self):
        self.assertAlmostEqual(saturation_pressure(273.16), 611.657, places=2)
        self.assertAlmostEqual(saturation_pressure(373.1243), 101325, delta=1)
        self.assertAlmostEqual(saturation_temperature(101325), 373.1243, places=3)
        with self.assertRaises(ValueError):
            saturation_pressure(700)

    def test_material_names_and_aliases(self):
        self.assertEqual(solid_name('Copper'), 'copper')
        self.assertEqual(solid_name(' OFHC copper '), 'copper')
        self.assertEqual(solid_name('Al 6061'), 'aluminum_6061')
        self.assertEqual(fluid_name('Water'), 'water')
        with self.assertRaises(ValueError):
            solid_name('unobtainium')

    def test_basis_matches_reference_calculation(self):
        basis = material_basis('copper', 'water', 283.15)
        self.assertAlmostEqual(basis['fluid_properties']['density_kg_m3'], 999.7018638961915, places=9)
        self.assertEqual(basis['solid_properties']['conductivity_W_m_K'], 394)
        self.assertEqual(basis['transport_model'], 'constant')

    def test_volumetric_units_and_energy(self):
        project = {'inlet_temperature_K': 283.15, 'heat_flux_W_m2': 1e7,
                   'outlet_absolute_pressure_bounds_Pa': [101325, 101325]}
        geometry = {'heated_area_m2': .002704,
                    'boundary_map': {'inlet': {'area_m2': 5.02654824574367e-5}},
                    'port_hydraulic_diameter_m': {'inlet': .008}}
        basis = material_basis('copper', 'water', 283.15)
        result = screen(project, geometry, basis, [1, 50])
        self.assertAlmostEqual(result['heat_input_W'], 27040, places=7)
        low, high = result['cases']
        self.assertAlmostEqual(high['mass_flow_kg_s'], .83308488658, places=10)
        self.assertFalse(low['bulk_single_phase_screen_pass'])
        self.assertTrue(high['bulk_single_phase_screen_pass'])
        cp = basis['fluid_properties']['cp_J_kg_K']
        self.assertAlmostEqual((high['bulk_outlet_heat_balance_K'] - 283.15) * high['mass_flow_kg_s'] * cp, 27040, places=7)


if __name__ == '__main__':
    unittest.main()
