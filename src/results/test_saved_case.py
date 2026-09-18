import json
import math
from pathlib import Path
import tempfile
import unittest

from src.results.export import cell_slices
from src.results.saved_case import verify_saved_inputs


class SavedCaseTests(unittest.TestCase):
    def test_tetra_plane_area_and_exact_cell_samples(self):
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
        cuts = cell_slices(points, faces, [0] * 4, [], {'T': [315.], 'p': [800000.]}, allowed_nodes=(4,))
        cut = next(c for c in cuts if c['axis'] == 'x' and c['position_mm'] == 500)
        coords = cut['positions_mm']
        area = 0
        for i in range(0, len(coords), 9):
            a, b, c = [coords[i + j:i + j + 3] for j in (0, 3, 6)]
            u = [b[k] - a[k] for k in range(3)]
            v = [c[k] - a[k] for k in range(3)]
            cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            area += math.sqrt(sum(x * x for x in cross)) / 2
        self.assertAlmostEqual(area, 125000.)
        self.assertTrue(all(x == 315 for x in cut['values']['T']))
        with self.assertRaises(ValueError):
            cell_slices(points, faces, [0] * 4, [], {'T': [315.]}, allowed_nodes=(8,))

    def test_stopped_status_and_review_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            case = run / 'case'
            (case / '10').mkdir(parents=True)
            records = {'manifest.json': {'execution_status': 'succeeded', 'simulation_executed': True},
                       'summary.json': {'latest_fields': '10'}, 'settings.json': {},
                       'bounded-review.json': {'status': 'iteration_limit_not_converged', 'chunks': [
                           {'iteration': 10, 'numerical_screen_pass': False, 'phase_margin_screen_pass': True,
                            'transport_validity': {'within_declared_range': True}}]}}
            for name, data in records.items():
                (case / name).write_text(json.dumps(data))
            decision, _, _ = verify_saved_inputs(run, 'case', '10')
            self.assertEqual(decision['status'], 'diagnostic')
            (case / '20').mkdir()
            with self.assertRaises(ValueError):
                verify_saved_inputs(run, 'case', '10')
            with self.assertRaises(ValueError):
                verify_saved_inputs(run, '../outside', '10')


if __name__ == '__main__':
    unittest.main()
