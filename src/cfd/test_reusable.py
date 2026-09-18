"""Warm start, operating search and settings derivation on synthetic data."""
import json
from pathlib import Path
import tempfile
import unittest

from src.cfd.operating_search import Point, next_flow
from src.cfd.settings import case_settings
from src.cfd.warm_start import seed_temperatures


class SearchTests(unittest.TestCase):
    @staticmethod
    def point(flow, pump_rise, temperature, physical=True):
        return Point(flow_L_min=flow, pump_pressure_rise_Pa=pump_rise, heated_temperature_K=temperature,
                     numerically_verified=True, physically_applicable=physical)

    def test_bad_model_cannot_bracket(self):
        p = self.point(50, 700000, 400, False)
        self.assertEqual(next_flow([p], [1, 50], 473.15, 800000)['status'], 'blocked_model_or_numerics')

    def test_pressure_resolution(self):
        a, b = self.point(20, 100000, 480), self.point(21, 109000, 470)
        self.assertEqual(next_flow([a, b], [1, 50], 473.15, 800000)['status'], 'bracketed')

    def test_nonmonotonic_response_not_accepted(self):
        a, b = self.point(20, 110000, 480), self.point(21, 109000, 470)
        self.assertEqual(next_flow([a, b], [1, 50], 473.15, 800000)['status'], 'review_nonmonotonic_response')

    def test_component_drop_api_cannot_silently_migrate(self):
        with self.assertRaises(TypeError):
            Point(50, 700000, 400, True, True)

    def test_pump_budget_not_component_loss_controls_limit(self):
        point = self.point(50, 790000 + 20000, 400)
        self.assertEqual(next_flow([point], [1, 50], 473.15, 800000)['status'], 'no_feasible_point_yet')


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.geometry = {'boundary_map': {'inlet': {'area_m2': 5.0265e-5}}, 'port_outward_normals': {'inlet': [1, 0, 0]},
                         'port_hydraulic_diameter_m': {'inlet': .008}, 'heated_area_m2': .002704}
        self.basis = {'fluid_properties': {'density_kg_m3': 999.7, 'cp_J_kg_K': 4195., 'dynamic_viscosity_Pa_s': .0013,
                                           'conductivity_W_m_K': .58}, 'solid': 'copper', 'fluid': 'water'}
        self.numerics = {'name': 'tet-robust', 'turbulence_model': 'kOmegaSST_spalding', 'velocity_relaxation': .3}

    def test_units_and_derived_quantities(self):
        operating = {'inlet_temperature_C': 10, 'outlet_absolute_pressure_bar': 8, 'volume_flow_L_min': 40,
                     'heat_flux_W_m2': 1e7, 'temperature_limit_C': 200}
        settings = case_settings(operating, self.geometry, self.basis, self.numerics, 500)
        self.assertAlmostEqual(settings['inlet_temperature_K'], 283.15)
        self.assertEqual(settings['outlet_absolute_pressure_Pa'], 800000)
        self.assertAlmostEqual(settings['mass_flow_kg_s'], 999.7 * 40 / 60000)
        self.assertEqual(settings['inlet_direction'], [-1., 0., 0.])
        self.assertAlmostEqual(settings['total_heat_load_W'], 27040)
        self.assertEqual(settings['turbulence_model'], 'kOmegaSST_spalding')
        self.assertEqual(settings['numerics_profile'], 'tet-robust')

    def test_total_heat_converts_to_flux_and_missing_flow_rejected(self):
        operating = {'inlet_temperature_K': 283.15, 'outlet_absolute_pressure_Pa': 101325, 'mass_flow_kg_s': .5,
                     'total_heat_load_W': 2704, 'temperature_limit_K': 473.15}
        settings = case_settings(operating, self.geometry, self.basis, self.numerics, 10)
        self.assertAlmostEqual(settings['heat_flux_W_m2'], 1e6)
        del operating['mass_flow_kg_s']
        with self.assertRaises(ValueError):
            case_settings(operating, self.geometry, self.basis, self.numerics, 10)


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'source'
        self.dst = Path(self.tmp.name) / 'target'
        for case in (self.src, self.dst):
            case.mkdir()
            (case / 'settings.json').write_text(json.dumps({'inlet_temperature_K': 283.15, 'heat_flux_W_m2': 1e7}))
            (case / 'manifest.json').write_text('{}')
            for region in ('fluid', 'solid'):
                poly = case / f'constant/{region}/polyMesh'
                poly.mkdir(parents=True)
                for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
                    (poly / name).write_text('FoamFile {}\n' + ('0()' if name == 'neighbour' else '1(0)'))
                path = case / f'{"100" if case == self.src else "0"}/{region}/T'
                path.parent.mkdir(parents=True)
                path.write_text('FoamFile {}\ninternalField uniform ' + ('350' if case == self.src else '283.15')
                                + ';\nboundaryField { inlet { value uniform 283.15; } }\n')

    def test_only_internal_temperature_copied(self):
        source = self.src / '100/fluid/T'
        source.write_text(source.read_text().replace('value uniform 283.15', 'value uniform 999'))
        seed_temperatures(self.src, self.dst)
        data = (self.dst / '0/fluid/T').read_text()
        self.assertIn('internalField uniform 350;', data)
        self.assertIn('value uniform 283.15;', data)
        self.assertNotIn('999', data)
        self.assertIn('temperature_initialization', json.loads((self.dst / 'manifest.json').read_text()))

    def test_invalid_second_region_never_partially_seeds(self):
        path = self.src / '100/solid/T'
        path.write_text(path.read_text().replace('uniform 350', 'uniform nan'))
        before = (self.dst / '0/fluid/T').read_text()
        with self.assertRaises(ValueError):
            seed_temperatures(self.src, self.dst)
        self.assertEqual(before, (self.dst / '0/fluid/T').read_text())
        self.assertFalse((self.dst / 'initial-temperature-original').exists())

    def test_mesh_change_rejected(self):
        (self.dst / 'constant/fluid/polyMesh/points').write_text('different')
        with self.assertRaises(ValueError):
            seed_temperatures(self.src, self.dst)

    def test_polynomial_fit_range_checked_before_initialization(self):
        path = self.dst / 'settings.json'
        settings = json.loads(path.read_text())
        settings['transport_polynomials'] = {'Tmin_K': 280, 'Tmax_K': 340}
        path.write_text(json.dumps(settings))
        with self.assertRaises(ValueError):
            seed_temperatures(self.src, self.dst)
        self.assertFalse((self.dst / 'initial-temperature-original').exists())

    def test_nonuniform_count_matches_mesh(self):
        path = self.src / '100/fluid/T'
        path.write_text(path.read_text().replace('uniform 350', 'nonuniform List<scalar> 2(350 351)'))
        with self.assertRaises(ValueError):
            seed_temperatures(self.src, self.dst)


if __name__ == '__main__':
    unittest.main()
