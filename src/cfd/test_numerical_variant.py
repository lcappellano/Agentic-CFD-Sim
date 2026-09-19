import json
from pathlib import Path
import tempfile
import unittest

from src.cfd.numerical_variant import clone


class NumericalVariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.target = Path(self.temp.name) / 'variant'
        for folder in ['constant/fluid/polyMesh', 'system/solid', 'system/fluid', '600/fluid', '600/solid']:
            (self.source / folder).mkdir(parents=True)
        for name in ['T', 'U', 'p', 'p_rgh', 'phi', 'rho', 'k', 'omega', 'nut', 'alphat']:
            (self.source / '600/fluid' / name).write_text('saved ' + name)
        (self.source / '600/solid/T').write_text('saved solid T')
        (self.source / 'constant/fluid/polyMesh/points').write_text('unchanged mesh')
        (self.source / 'system/solid/fvSolution').write_text('relaxationFactors { equations { h 0.3; } }')
        (self.source / 'system/fluid/fvSolution').write_text('solvers { h { tolerance 1e-8; } } relaxationFactors { fields { p_rgh 0.2; } equations { U 0.3; h 0.3; k 0.7; } }')
        (self.source / 'settings.json').write_text(json.dumps({'solid_enthalpy_relaxation': .3, 'fluid_enthalpy_relaxation': .3, 'heat_flux_W_m2': 1e7, 'turbulence_model': 'kOmegaSST_spalding'}))
        (self.source / 'manifest.json').write_text(json.dumps({'simulation_executed': True, 'solver_logs': ['old']}))
        self.review = {'status': 'iteration_limit_not_converged', 'chunks': [{'iteration': 600., 'phase_margin_screen_pass': True, 'transport_validity': {'within_declared_range': True}}]}
        self.save_review()

    def save_review(self):
        (self.source / 'bounded-review.json').write_text(json.dumps(self.review))

    def test_only_relaxation_changes_and_full_restart_state_is_preserved(self):
        provenance = clone(self.source, self.target, '600', .9)
        self.assertEqual((self.target / '0/fluid/phi').read_bytes(), (self.source / '600/fluid/phi').read_bytes())
        self.assertEqual((self.target / '0/fluid/rho').read_bytes(), (self.source / '600/fluid/rho').read_bytes())
        self.assertIn('h 0.9;', (self.target / 'system/solid/fvSolution').read_text())
        self.assertIn('h 0.3;', (self.source / 'system/solid/fvSolution').read_text())
        self.assertEqual(json.loads((self.target / 'settings.json').read_text())['heat_flux_W_m2'], 1e7)
        self.assertFalse(json.loads((self.target / 'manifest.json').read_text())['simulation_executed'])
        self.assertFalse(provenance['physical_fields_and_boundary_conditions_changed'])
        self.assertFalse((self.target / 'bounded-review.json').exists())

    def test_invalid_or_unreviewed_source_rejected_without_partial_target(self):
        for key in ['phase_margin_screen_pass']:
            self.review['chunks'][0][key] = False
        self.save_review()
        with self.assertRaises(ValueError):
            clone(self.source, self.target, '600', .9)
        self.assertFalse(self.target.exists())

    def test_both_energy_equations_change_without_momentum_or_pressure(self):
        result = clone(self.source, self.target, '600', .9, .9)
        solution = (self.target / 'system/fluid/fvSolution').read_text()
        self.assertIn('equations { U 0.3; h 0.9; k 0.7; }', solution)
        self.assertIn('fields { p_rgh 0.2; }', solution)
        self.assertIn('solvers { h { tolerance 1e-8; } }', solution)
        self.assertEqual(set(result['changes']), {'solid_enthalpy_relaxation', 'fluid_enthalpy_relaxation'})

    def test_laminar_checkpoint_needs_no_turbulence_fields(self):
        settings = json.loads((self.source / 'settings.json').read_text())
        settings['turbulence_model'] = 'laminar'
        (self.source / 'settings.json').write_text(json.dumps(settings))
        for name in ['k', 'omega', 'nut', 'alphat']:
            (self.source / '600/fluid' / name).unlink()
        clone(self.source, self.target, '600', 1.0, 1.0)
        self.assertIn('h 1.0;', (self.target / 'system/solid/fvSolution').read_text())

    def test_constant_transport_checkpoint_is_clonable(self):
        self.review['chunks'][0]['transport_validity'] = {'within_declared_range': None, 'model': 'constant'}
        self.save_review()
        clone(self.source, self.target, '600', .9)
        self.assertTrue((self.target / '0/fluid/T').exists())

    def test_bad_relaxation_and_missing_state_rejected(self):
        for value in [True, float('nan'), 0, 1.1]:
            with self.assertRaises(ValueError):
                clone(self.source, self.target, '600', value)
        (self.source / '600/fluid/phi').unlink()
        with self.assertRaises(ValueError):
            clone(self.source, self.target, '600', .9)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
