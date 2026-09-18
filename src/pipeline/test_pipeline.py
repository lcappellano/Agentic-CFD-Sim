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

    def test_operating_point_may_be_left_for_the_operator(self):
        resolved = spec_module.resolve(spec_module.load(self.write({'prescreen': {'flow_range_L_min': [1, 20], 'points': 4}})), self.root)
        self.assertEqual(missing_operating_point(resolved['operating']), ['operating.volume_flow_L_min (or mass_flow_kg_s)'])
        self.assertEqual(resolved['prescreen']['flow_range_L_min'], [1, 20])
        self.assertEqual(resolved['prescreen']['wall_subcooling_margin_K'], 10)
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'prescreen': {'flows_lpm': [1]}})), self.root)

    def test_unknown_keys_and_profiles_rejected(self):
        with self.assertRaises(ValueError):
            spec_module.load(self.write({'operatng': {}}))
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'numerics': {'profile': 'nope'}})), self.root)
        with self.assertRaises(ValueError):
            spec_module.resolve(spec_module.load(self.write({'numerics': {'overrides': {'bogus': 1}}})), self.root)

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

    def test_block_fixture_runs_every_stage(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_fixture'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        synthetic_handoff(root / 'handoff')
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e', 'unapproved_handoff_ok': True,
                'prescreen': {'flow_range_L_min': [5, 40], 'points': 4, 'outlet_pressures_bar': [1.11325, 3]},
                'mesh': {'profile': 'tet-test'}, 'numerics': {'profile': 'tet-robust'},
                'acceptance': {'profile': 'test-loose'},
                'schedule': {'initial': 20, 'chunk': 20, 'maximum': 40, 'ranks': 2}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', log=lambda *_: None)
        self.assertEqual(state['status'], 'awaiting_operator_decision')
        self.assertEqual(state['stages']['prescreen']['status'], 'done')
        self.assertEqual(state['stages']['mesh']['status'], 'pending')
        self.assertIn('Suggested CFD starting point', state['stages']['prescreen']['table'])
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


if __name__ == '__main__':
    unittest.main()
