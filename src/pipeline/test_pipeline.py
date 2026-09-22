"""Spec resolution, profiles, state summary and (optionally) the full solver fixture."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from src.pipeline import spec as spec_module, state as state_module
from src.pipeline.spec import missing_operating_point
from src.pipeline.fixtures import synthetic_handoff
from src.pipeline.report import write_report

ROOT = Path(__file__).resolve().parents[2]


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        synthetic_handoff(self.root / 'handoff')

    def write(self, spec):
        path = self.root / 'spec.json'
        path.write_text(json.dumps({'schema_version': 1, 'handoff': 'handoff', **spec}))
        return path

    def test_defaults_come_from_handoff_and_profiles(self):
        resolved = spec_module.resolve(spec_module.load(self.write({'operating': {'mass_flow_kg_s': .5}})), self.root)
        self.assertEqual(resolved['operating']['inlet_temperature_K'], 300)
        self.assertEqual(resolved['operating']['heat_flux_W_m2'], 100000)
        self.assertEqual(resolved['operating']['outlet_absolute_pressure_Pa'], 111325)
        self.assertEqual(resolved['operating']['temperature_limit_K'], 500)
        self.assertEqual(resolved['materials']['solid'], 'copper')
        self.assertEqual(resolved['numerics']['name'], 'tet-robust')
        self.assertEqual(resolved['mesh']['name'], 'tet-coarse')
        self.assertEqual(resolved['acceptance']['final_window_iterations'], 100)
        self.assertEqual(resolved['schedule']['maximum'], 2000)

    def test_spec_values_override_handoff_in_any_unit(self):
        spec = {'operating': {'volume_flow_L_min': 30, 'inlet_temperature_C': 20, 'outlet_absolute_pressure_bar': 3},
                'numerics': {'profile': 'hex-kepsilon', 'overrides': {'velocity_relaxation': .5}},
                'mesh': {'profile': 'tet-fine', 'overrides': {'wall_size_m': .0002}}}
        resolved = spec_module.resolve(spec_module.load(self.write(spec)), self.root)
        self.assertEqual(resolved['operating']['inlet_temperature_C'], 20)
        self.assertNotIn('inlet_temperature_K', resolved['operating'])
        self.assertEqual(resolved['numerics']['velocity_relaxation'], .5)
        self.assertEqual(resolved['numerics']['turbulence_model'], 'kEpsilon')
        self.assertEqual(resolved['mesh']['wall_size_m'], .0002)

    def test_operating_point_may_be_left_open(self):
        resolved = spec_module.resolve(spec_module.load(self.write({'prescreen': {'flow_range_L_min': [1, 20], 'points': 4},
                                                                    'decision': {'required': True}})), self.root)
        self.assertEqual(missing_operating_point(resolved['operating']), ['operating.volume_flow_L_min (or mass_flow_kg_s)'])
        self.assertEqual(resolved['prescreen']['flow_range_L_min'], [1, 20])
        self.assertEqual(resolved['prescreen']['wall_subcooling_margin_K'], 10)
        self.assertIs(resolved['decision']['required'], True)
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'prescreen': {'flows_lpm': [1]}})), self.root)

    def test_equal_review_bounds_fix_the_value_unless_the_spec_sets_it(self):
        synthetic_handoff(self.root / 'handoff-fixed', flow_bounds=(.5, .5))
        path = self.root / 'spec.json'
        path.write_text(json.dumps({'schema_version': 1, 'handoff': 'handoff-fixed'}))
        resolved = spec_module.resolve(spec_module.load(path), self.root)
        self.assertEqual(resolved['operating']['mass_flow_kg_s'], .5)
        self.assertEqual(missing_operating_point(resolved['operating']), [])
        path.write_text(json.dumps({'schema_version': 1, 'handoff': 'handoff-fixed', 'operating': {'volume_flow_L_min': 30, 'total_heat_load_W': 5}}))
        resolved = spec_module.resolve(spec_module.load(path), self.root)
        self.assertNotIn('mass_flow_kg_s', resolved['operating'])
        self.assertNotIn('heat_flux_W_m2', resolved['operating'])
        synthetic_handoff(self.root / 'handoff-blank', pressure_bounds=None)
        path.write_text(json.dumps({'schema_version': 1, 'handoff': 'handoff-blank'}))
        resolved = spec_module.resolve(spec_module.load(path), self.root)
        self.assertEqual(len(missing_operating_point(resolved['operating'])), 2)

    def test_unknown_keys_and_profiles_rejected(self):
        with self.assertRaises(ValueError):
            spec_module.load(self.write({'operatng': {}}))
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'numerics': {'profile': 'nope'}})), self.root)
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'numerics': {'overrides': {'bogus': 1}}})), self.root)

    def test_restart_initialization_keys_and_profile(self):
        resolved = spec_module.resolve(spec_module.load(self.write({'initialization': {'fields_from_case': 'runs/x/cases/case-1'},
                                                                    'numerics': {'profile': 'tet-robust-restart'}})), self.root)
        self.assertEqual(resolved['initialization']['fields_from_case'], 'runs/x/cases/case-1')
        self.assertEqual(resolved['numerics']['solid_gradient'], 'Gauss linear')
        self.assertEqual(resolved['numerics']['turbulence_model'], 'kOmegaSST_spalding')
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'initialization': {'fields_from_case': 'a', 'temperature_from_case': 'b'}})), self.root)
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'initialization': {'fields_from_case': 'a', 'fields_mapped_from_case': 'b'}})), self.root)
        resolved = spec_module.resolve(spec_module.load(self.write({'initialization': {'fields_mapped_from_case': 'runs/x/cases/case-1'}})), self.root)
        self.assertEqual(resolved['initialization']['fields_mapped_from_case'], 'runs/x/cases/case-1')

    def test_report_advice_for_a_residual_floor(self):
        state = state_module.load(self.root)
        state['run'] = 'run-1'
        state['spec'] = {'numerics': {'solid_gradient': 'cellLimited Gauss linear 1'}}
        state['case'] = {'status': 'diagnostic', 'stop_reason': 'iteration_limit_not_converged', 'iteration': 3000, 'path': 'cases/case-a',
                         'heated_maximum_C': 154.4, 'heated_maximum_K': 427.5, 'temperature_limit_C': 200, 'wetted_maximum_C': 132.8,
                         'pressure_drop_bar': 2.83, 'total_pressure_drop_bar': 2.78,
                         'numerical_checks': {'mass': True, 'energy': True, 'temperature_drift': True, 'pressure_drift': False, 'residuals': False},
                         'audit_failed': ['pressure_drop_stability', 'residual:fluid:p_rgh', 'residual:solid:h']}
        report = write_report(self.root, state)
        self.assertNotIn('Raise schedule.maximum', report)
        self.assertIn('will not help', report)
        self.assertIn('tet-robust-restart', report)
        self.assertIn('fields_from_case: runs/run-1/cases/case-a', report)
        self.assertIn('finer mesh', report)
        state['spec']['numerics']['solid_gradient'] = 'Gauss linear'
        state['case']['audit_failed'] = ['residual:solid:h']
        state['case']['numerical_checks']['pressure_drift'] = True
        report = write_report(self.root, state)
        self.assertNotIn('tet-robust-restart', report)
        self.assertIn('unlimited gradient', report)

    def test_state_summary_and_report(self):
        state = state_module.load(self.root)
        state['stages']['geometry'].update(status='done', output='geometry/geo-1', summary={'fluid_m3': '3e-6'})
        state['case'] = {'status': 'diagnostic', 'stop_reason': 'iteration_limit_not_converged', 'iteration': 40,
                         'heated_maximum_C': 35.1, 'heated_maximum_K': 308.25, 'temperature_limit_C': 226.85,
                         'wetted_maximum_C': 31.8, 'pressure_drop_bar': .087, 'total_pressure_drop_bar': .09,
                         'numerical_checks': {'mass': True, 'energy': False}}
        text = state_module.summary_text(state)
        self.assertIn('geometry   done', text)
        self.assertIn('failed checks: energy', text)
        self.assertLess(len(text), 1024)
        report = write_report(self.root, state)
        self.assertIn('Raise schedule.maximum', report)


@unittest.skipUnless(os.environ.get('WORKBENCH_E2E'), 'set WORKBENCH_E2E=1 to run the solver fixture')
class EndToEndTests(unittest.TestCase):
    """Real Gmsh + OpenFOAM on the synthetic block: a minute, not an engineering result."""

    def test_laminar_point_selects_laminar_profile_and_solves(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_laminar'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-laminar', 'unapproved_handoff_ok': True,
                'operating': {'mass_flow_kg_s': .005}, 'mesh': {'profile': 'tet-test'},
                'acceptance': {'profile': 'test-loose'}, 'schedule': {'initial': 20, 'chunk': 20, 'maximum': 40, 'ranks': 2}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'complete', state['stages'])
        self.assertEqual(state['spec']['numerics']['name'], 'laminar')
        self.assertTrue(any('switched to laminar' in w for w in state['warnings']))
        case = root / 'runs' / Path(state['run']).name / state['stages']['case']['output']
        self.assertIn('simulationType laminar', (case / 'constant/fluid/turbulenceProperties').read_text())
        self.assertFalse((case / '0/fluid/k').exists())
        self.assertGreater(state['case']['heated_maximum_K'], 300)
        shutil.rmtree(root)

    def test_block_fixture_runs_every_stage(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_fixture'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e', 'unapproved_handoff_ok': True,
                'prescreen': {'flow_range_L_min': [5, 40], 'points': 4, 'outlet_pressures_bar': [1.11325, 3]},
                'decision': {'required': True}, 'mesh': {'profile': 'tet-test'}, 'numerics': {'profile': 'tet-robust'},
                'acceptance': {'profile': 'test-loose'},
                'schedule': {'initial': 20, 'chunk': 20, 'maximum': 40, 'ranks': 2}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'awaiting_operator_decision')
        self.assertEqual(state['stages']['prescreen']['status'], 'done')
        self.assertEqual(state['stages']['mesh']['status'], 'pending')
        self.assertIn('Estimated operating point', state['stages']['prescreen']['table'])
        self.assertIn('Prescreen estimate', state['decision_prompt'])
        run = root / 'runs' / Path(state['run']).name
        self.assertIn('Decision needed', (run / 'report.md').read_text())
        spec['operating'] = {'mass_flow_kg_s': .5}
        spec['decision'] = {'operator': 'e2e test', 'note': 'fixture point'}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', run=run, log=lambda *_: None)
        self.assertEqual(state['status'], 'complete')
        self.assertTrue(state['stages']['geometry']['cached'])
        statuses = {name: stage['status'] for name, stage in state['stages'].items()}
        self.assertEqual(set(statuses.values()), {'done'}, statuses)
        self.assertIn(state['case']['status'], ('diagnostic', 'numerically_screened'))
        self.assertGreater(state['case']['heated_maximum_K'], 300)
        self.assertTrue((run / 'report.md').is_file())
        # A second call with a larger maximum must reuse every stage before the solve.
        spec['schedule']['maximum'] = 60
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', run=run, log=lambda *_: None)
        self.assertTrue(state['stages']['mesh']['cached'])
        self.assertTrue(state['stages']['case']['cached'])
        self.assertEqual(state['case']['iteration'], 60)
        shutil.rmtree(root)

    def test_hxt_mesher_reports_quality_and_rejects_a_floor_above_its_best(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_mesh_quality'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-mesh', 'unapproved_handoff_ok': True,
                'operating': {'mass_flow_kg_s': .5}, 'mesh': {'profile': 'tet-test', 'overrides': {'algorithm_3d': 10, 'threads': 2}},
                'acceptance': {'profile': 'test-loose'}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', until='mesh', log=lambda *_: None)
        self.assertEqual(state['status'], 'stopped_after_mesh', state['stages'])
        run = root / 'runs' / Path(state['run']).name
        metadata = json.loads((run / state['stages']['mesh']['output']).with_suffix('.json').read_text())
        quality = metadata['quality']
        self.assertEqual(quality['metric'], 'minSICN')
        self.assertEqual(quality['passes'][0], 'HXT + Gmsh optimiser')
        self.assertEqual(set(quality['regions']), {'fluid', 'solid'})
        self.assertTrue(all(q['min'] >= quality['floor'] for q in quality['regions'].values()), quality)
        self.assertEqual(state['stages']['mesh']['summary']['min_sicn'], round(min(q['min'] for q in quality['regions'].values()), 4))
        # A floor no tetrahedral mesh reaches must fail the mesh stage, before any case is built.
        spec['mesh']['overrides'] = {'algorithm_3d': 10, 'threads': 2, 'min_quality': .999, 'optimize_netgen': False}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', run=run, until='mesh', log=lambda *_: None)
        self.assertEqual(state['status'], 'failed')
        self.assertIn('Mesh quality below the floor', state['stages']['mesh']['error'])
        self.assertEqual(state['stages']['case']['status'], 'pending')
        shutil.rmtree(root)

    def test_mapped_start_on_a_different_mesh_skips_the_potential_start(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_mapped'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-mapped', 'unapproved_handoff_ok': True,
                'operating': {'mass_flow_kg_s': .5}, 'mesh': {'profile': 'tet-test'}, 'numerics': {'profile': 'tet-robust'},
                'acceptance': {'profile': 'test-loose'}, 'schedule': {'initial': 20, 'chunk': 20, 'maximum': 20, 'ranks': 2}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'complete', state['stages'])
        run = root / 'runs' / Path(state['run']).name
        coarse = state['stages']['case']['output']
        spec['mesh'] = {'profile': 'tet-test', 'overrides': {'wall_size_per_diameter': .2, 'bulk_size_per_diameter': .45}}
        spec['initialization'] = {'fields_mapped_from_case': f'runs/{run.name}/{coarse}'}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', run=run, log=lambda *_: None)
        self.assertEqual(state['status'], 'complete', state['stages'])
        self.assertFalse(state['stages']['mesh']['cached'])
        fine = run / state['stages']['case']['output']
        self.assertNotEqual(state['stages']['case']['output'], coarse)
        manifest = json.loads((fine / 'manifest.json').read_text())
        self.assertNotIn('velocity_initialization', manifest)
        mapped = manifest['mapped_initialization']
        self.assertEqual(mapped['source_iteration'], '20')
        self.assertTrue({'U', 'p', 'p_rgh', 'T'} <= set(mapped['fields']['fluid']), mapped['fields'])
        self.assertIn('T', mapped['fields']['solid'])
        self.assertTrue(mapped['fields']['fluid']['T']['nonuniform'])
        self.assertFalse((fine / '0/fluid/yPlus').exists())
        self.assertIn('mapped from', state['stages']['case']['summary']['fields_init'])
        self.assertGreater(state['case']['heated_maximum_K'], 300)
        shutil.rmtree(root)

    def test_restart_seeds_every_field_and_skips_the_potential_start(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_restart'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-restart', 'unapproved_handoff_ok': True,
                'operating': {'mass_flow_kg_s': .5}, 'mesh': {'profile': 'tet-test'}, 'numerics': {'profile': 'tet-robust'},
                'acceptance': {'profile': 'test-loose'}, 'schedule': {'initial': 20, 'chunk': 20, 'maximum': 20, 'ranks': 2}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'complete', state['stages'])
        run = root / 'runs' / Path(state['run']).name
        first = state['stages']['case']['output']
        self.assertIn('velocity_initialization', json.loads((run / first / 'manifest.json').read_text()))
        spec['numerics'] = {'profile': 'tet-robust-restart'}
        spec['initialization'] = {'fields_from_case': f'runs/{run.name}/{first}'}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', run=run, log=lambda *_: None)
        self.assertEqual(state['status'], 'complete', state['stages'])
        self.assertTrue(state['stages']['mesh']['cached'])
        self.assertFalse(state['stages']['case']['cached'])
        self.assertNotEqual(state['stages']['case']['output'], first)
        second = run / state['stages']['case']['output']
        manifest = json.loads((second / 'manifest.json').read_text())
        self.assertNotIn('velocity_initialization', manifest)
        seeded = manifest['fields_initialization']['fields']
        self.assertTrue({'U', 'p', 'p_rgh', 'T', 'k', 'omega'} <= set(seeded['fluid']), seeded)
        self.assertNotIn('phi', seeded['fluid'])
        self.assertEqual(set(seeded['solid']), {'T', 'p'})
        self.assertIn('gradSchemes { default Gauss linear; }', (second / 'system/solid/fvSchemes').read_text())
        self.assertEqual(state['stages']['case']['summary']['fields_init'], spec['initialization']['fields_from_case'])
        self.assertGreater(state['case']['heated_maximum_K'], 300)
        shutil.rmtree(root)

    def test_blank_review_bounds_are_autofilled_before_the_case_is_built(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_autofill'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff', pressure_bounds=None)
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-autofill', 'unapproved_handoff_ok': True,
                'mesh': {'profile': 'tet-test'}, 'acceptance': {'profile': 'test-loose'}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', until='case', log=lambda *_: None)
        self.assertEqual(state['status'], 'stopped_after_case', state['stages'])
        filled = state['autofill']['filled']
        self.assertEqual(set(filled), {'volume_flow_L_min', 'outlet_absolute_pressure_Pa'})
        self.assertEqual(state['spec']['operating']['volume_flow_L_min'], filled['volume_flow_L_min'])
        run = root / 'runs' / Path(state['run']).name
        settings = json.loads((run / state['stages']['case']['output'] / 'settings.json').read_text())
        self.assertAlmostEqual(settings['volume_flow_L_min'], filled['volume_flow_L_min'])
        self.assertAlmostEqual(settings['outlet_absolute_pressure_Pa'], filled['outlet_absolute_pressure_Pa'])
        self.assertIn('autofill:', state_module.summary_text(state))
        write_report(run, state, None)
        self.assertIn('Estimated operating point', (run / 'report.md').read_text())
        shutil.rmtree(root)

    def test_implausible_estimate_stops_for_the_operator_instead_of_capping(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_stop'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff', pressure_bounds=None, flow_bounds=(5., 50.))  # 5 kg/s floor: far beyond plausible velocity
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-stop', 'unapproved_handoff_ok': True,
                'mesh': {'profile': 'tet-test'}, 'acceptance': {'profile': 'test-loose'}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'awaiting_operator_decision')
        self.assertEqual(state['stages']['mesh']['status'], 'pending')
        self.assertNotIn('autofill', state)
        self.assertIn('needs operator input', state['decision_prompt'])
        self.assertIn("lower flow bound", state['decision_prompt'])
        self.assertIn('STOP:', state['stages']['prescreen']['table'])
        estimate = state['stages']['prescreen']['result']['autofill']
        self.assertGreater(estimate['estimate']['mean_speed_m_s'], 10)  # reported as needed, not lowered
        spec['prescreen'] = {'plausible_velocity_m_s': 1000, 'plausible_pressure_drop_Pa': 1e9}
        (root / 'spec.json').write_text(json.dumps(spec))
        run = root / 'runs' / Path(state['run']).name
        state = simulate(root, root / 'spec.json', run=run, until='prescreen', log=lambda *_: None)
        self.assertEqual(state['status'], 'stopped_after_prescreen')
        self.assertAlmostEqual(state['autofill']['filled']['volume_flow_L_min'], estimate['volume_flow_L_min'], places=2)  # filled to 6 figures
        shutil.rmtree(root)


if __name__ == '__main__':
    unittest.main()
