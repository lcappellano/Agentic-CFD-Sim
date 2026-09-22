"""Warm start, operating search and settings derivation on synthetic data."""
import json
from pathlib import Path
import tempfile
import unittest

from src.cfd.operating_search import Point, next_flow
from src.cfd.settings import case_settings
from src.cfd.map_fields import check_compatible, map_from_case
from src.cfd.warm_start import seed_temperatures, seed_fields


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


class FieldSeedingTests(unittest.TestCase):
    """Restart seeding: every shared field, never phi, target boundaries kept."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'source'
        self.dst = Path(self.tmp.name) / 'target'
        settings = {'inlet_temperature_K': 283.15, 'heat_flux_W_m2': 1e7, 'mass_flow_kg_s': .5, 'outlet_absolute_pressure_Pa': 8e5}
        for case in (self.src, self.dst):
            case.mkdir()
            (case / 'settings.json').write_text(json.dumps(settings))
            (case / 'manifest.json').write_text('{}')
            for region in ('fluid', 'solid'):
                poly = case / f'constant/{region}/polyMesh'
                poly.mkdir(parents=True)
                for name in ('points', 'faces', 'owner', 'neighbour', 'boundary'):
                    (poly / name).write_text('FoamFile {}\n' + ('0()' if name == 'neighbour' else '1(0)'))
            solved = case == self.src
            fluid, solid = case / ('200' if solved else '0') / 'fluid', case / ('200' if solved else '0') / 'solid'
            fluid.mkdir(parents=True)
            solid.mkdir(parents=True)
            self.field(fluid / 'T', 'uniform 350' if solved else 'uniform 283.15', 'value uniform 283.15')
            self.field(fluid / 'U', 'nonuniform List<vector> 1((1 2 3))' if solved else 'uniform (0 0 0)',
                       'value uniform (7 7 7)' if solved else 'value uniform (0 0 0)')
            self.field(fluid / 'p', 'nonuniform List<scalar> 1(812345)' if solved else 'uniform 800000', 'value uniform 800000')
            self.field(solid / 'T', 'uniform 400' if solved else 'uniform 283.15', 'value uniform 283.15')
            if solved:
                self.field(fluid / 'phi', 'nonuniform List<scalar> 0()', 'value uniform 0')
                self.field(fluid / 'yPlus', 'uniform 50', 'value uniform 50')

    @staticmethod
    def field(path, internal, boundary):
        path.write_text(f'FoamFile {{}}\ninternalField {internal};\nboundaryField {{ inlet {{ {boundary}; }} }}\n')

    def test_shared_fields_seeded_phi_and_postprocessing_skipped(self):
        records = seed_fields(self.src, self.dst)
        self.assertEqual(set(records['fluid']), {'T', 'U', 'p'})
        self.assertEqual(set(records['solid']), {'T'})
        u = (self.dst / '0/fluid/U').read_text()
        self.assertIn('internalField nonuniform List<vector> 1((1 2 3));', u)
        self.assertIn('value uniform (0 0 0);', u)
        self.assertNotIn('(7 7 7)', u)
        self.assertIn('internalField nonuniform List<scalar> 1(812345);', (self.dst / '0/fluid/p').read_text())
        self.assertIn('internalField uniform 350;', (self.dst / '0/fluid/T').read_text())
        self.assertIn('internalField uniform 400;', (self.dst / '0/solid/T').read_text())
        self.assertFalse((self.dst / '0/fluid/phi').exists())
        self.assertFalse((self.dst / '0/fluid/yPlus').exists())
        self.assertTrue((self.dst / 'initial-fields-original/fluid/U').is_file())
        manifest = json.loads((self.dst / 'manifest.json').read_text())
        self.assertEqual(manifest['fields_initialization']['source_iteration'], '200')
        with self.assertRaises(ValueError):
            seed_fields(self.src, self.dst)

    def test_operating_point_must_match_for_a_restart(self):
        path = self.dst / 'settings.json'
        settings = json.loads(path.read_text())
        settings['mass_flow_kg_s'] = .6
        path.write_text(json.dumps(settings))
        with self.assertRaises(ValueError):
            seed_fields(self.src, self.dst)
        self.assertIn('internalField uniform (0 0 0);', (self.dst / '0/fluid/U').read_text())
        # A temperature-only seed at a new flow is still allowed and leaves U alone.
        seed_temperatures(self.src, self.dst)
        self.assertIn('internalField uniform 350;', (self.dst / '0/fluid/T').read_text())
        self.assertIn('internalField uniform (0 0 0);', (self.dst / '0/fluid/U').read_text())

    def test_vector_size_and_finiteness_checked_before_any_write(self):
        path = self.src / '200/fluid/U'
        for bad in ('nonuniform List<vector> 2((1 2 3) (4 5 6))', 'nonuniform List<vector> 1((1 nan 3))'):
            self.field(path, bad, 'value uniform (7 7 7)')
            with self.assertRaises(ValueError):
                seed_fields(self.src, self.dst)
            self.assertIn('internalField uniform 283.15;', (self.dst / '0/fluid/T').read_text())
            self.assertFalse((self.dst / 'initial-fields-original').exists())


class MappedStartTests(unittest.TestCase):
    """Pre-checks of the mesh-change initialisation; mapFields itself is covered by the e2e fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'source'
        self.dst = Path(self.tmp.name) / 'target'
        settings = {'inlet_temperature_K': 283.15, 'heat_flux_W_m2': 1e7, 'mass_flow_kg_s': .5, 'outlet_absolute_pressure_Pa': 8e5}
        for case in (self.src, self.dst):
            case.mkdir()
            (case / 'settings.json').write_text(json.dumps(settings))
            (case / 'geometry-manifest.json').write_text(json.dumps({'source_sha256': 'step', 'requirements_sha256': 'req'}))
            (case / 'manifest.json').write_text('{}')
            (case / ('300' if case == self.src else '0')).mkdir()

    def test_compatible_cases_return_the_source_time(self):
        self.assertEqual(check_compatible(self.src, self.dst).name, '300')

    def test_rejects_other_geometry_operating_point_or_used_target(self):
        (self.dst / 'geometry-manifest.json').write_text(json.dumps({'source_sha256': 'other', 'requirements_sha256': 'req'}))
        with self.assertRaises(ValueError):
            check_compatible(self.src, self.dst)
        (self.dst / 'geometry-manifest.json').write_text((self.src / 'geometry-manifest.json').read_text())
        settings = json.loads((self.dst / 'settings.json').read_text())
        settings['outlet_absolute_pressure_Pa'] = 2e5
        (self.dst / 'settings.json').write_text(json.dumps(settings))
        with self.assertRaises(ValueError):
            check_compatible(self.src, self.dst)
        (self.dst / 'settings.json').write_text((self.src / 'settings.json').read_text())
        (self.dst / '50').mkdir()
        with self.assertRaises(ValueError):
            check_compatible(self.src, self.dst)
        with self.assertRaises(ValueError):
            map_from_case(self.src, self.dst, method='bogus')


if __name__ == '__main__':
    unittest.main()
