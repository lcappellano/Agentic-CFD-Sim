"""Gate logic of the bounded driver on synthetic evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.cfd.run_bounded import phase_counts, stop_reason, execute
from src.cfd.transport import validate_polynomials
from src.cfd.turbulence import setup
from src.foam.logs import residual_maxima
from src.foam.monitors import full_window


class BoundedTests(unittest.TestCase):
    def test_solver_failure_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / 'case'
            case.mkdir()
            criteria = {'final_window_iterations': 100}
            with patch('src.cfd.run_bounded.run', side_effect=RuntimeError('solver failed')):
                with self.assertRaises(RuntimeError):
                    execute(case, criteria, maximum=100)
            record = json.loads((case / 'bounded-review.json').read_text())
            self.assertEqual(record['status'], 'solver_or_postprocessing_failed')
            self.assertEqual(record['error']['message'], 'solver failed')

    def test_sparse_monitor_window_rejected(self):
        self.assertFalse(full_window([(0, []), (100, [])], 100, 100))
        self.assertFalse(full_window([(t, []) for t in range(10, 101, 10)], 100, 100))
        self.assertTrue(full_window([(t, []) for t in range(0, 101, 10)], 100, 100))

    def test_nonfinite_residual_is_never_hidden_by_max(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'log.solver').write_text('Time = 100\nSolving for fluid region fluid\n'
                                              'GAMG: Solving for p_rgh, Initial residual = nan, Final residual = 0, No Iterations 1\n')
            values = residual_maxima(path, 100, 100)['fluid:p_rgh']
            self.assertFalse(values['finite'])
            self.assertFalse(values['window_complete'])

    def test_sst_changes_dissipation_and_wall_treatment(self):
        old = setup('kEpsilon', 10, .05, .00056)
        new = setup('kOmegaSST_spalding', 10, .05, .00056)
        self.assertEqual(new['RASModel'], 'kOmegaSST')
        self.assertEqual(old['fields'][0][1], new['fields'][0][1])
        fields = {row[0]: row for row in new['fields']}
        self.assertNotIn('epsilon', fields)
        self.assertGreater(fields['omega'][1], 0)
        self.assertIn('Spalding', fields['nut'][3])
        self.assertIn('blended true', fields['omega'][3])

    def test_boolean_polynomial_rejected(self):
        spec = {'Tmin_K': 280, 'Tmax_K': 380, 'muCoeffs8': [True] + [0.] * 7, 'kappaCoeffs8': [.6] + [0.] * 7}
        with self.assertRaises(ValueError):
            validate_polynomials(spec)

    def test_saturation_buffer_distinct_from_boiling(self):
        values = phase_counts([370], [101325], 10)
        self.assertEqual(values['above_saturation'], 0)
        self.assertEqual(values['below_required_margin'], 1)

    def test_single_phase_failure_requires_persistence(self):
        phase = phase_counts([400], [101325], 10)
        evidence = {'phase': {'wetted': phase}, 'transport_validity': {'within_declared_range': True}, 'numerical_screen_pass': False}
        reason, failed = stop_reason(evidence, False)
        self.assertIsNone(reason)
        self.assertTrue(failed)
        reason, _ = stop_reason(evidence, True)
        self.assertIn('not_design_failure', reason)

    def test_property_range_stops_even_before_convergence(self):
        evidence = {'phase': {'bulk': phase_counts([300], [101325], 10)},
                    'transport_validity': {'within_declared_range': False}, 'numerical_screen_pass': False}
        self.assertEqual(stop_reason(evidence, False)[0], 'outside_transport_fit_range')


if __name__ == '__main__':
    unittest.main()
