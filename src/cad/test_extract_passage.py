"""Extraction regression on the analytic through-bore block (needs the Gmsh runtime)."""
import json
import math
from pathlib import Path
import tempfile
import unittest

from src.cad.extract_passage import extract
from src.pipeline.fixtures import synthetic_handoff


class ExtractPassageTests(unittest.TestCase):
    def test_block_volumes_normals_and_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            handoff = synthetic_handoff(Path(tmp) / 'handoff')
            manifest = extract(handoff, Path(tmp) / 'geometry')
            bore = math.pi * .004 ** 2 * .06
            self.assertAlmostEqual(manifest['regions']['fluid']['volume_m3'], bore, places=12)
            self.assertAlmostEqual(manifest['regions']['solid']['volume_m3'], .06 * .04 * .02 - bore, places=12)
            self.assertAlmostEqual(manifest['heated_area_m2'], .0024, places=12)
            self.assertAlmostEqual(manifest['heated_to_passage_distance_m'], .006, places=9)
            self.assertEqual(manifest['port_outward_normals']['inlet'], [-1., 0., -0.])
            self.assertEqual(manifest['port_outward_normals']['outlet'], [1., -0., 0.])
            self.assertAlmostEqual(manifest['port_hydraulic_diameter_m']['inlet'], .008, places=9)
            self.assertEqual(len(manifest['boundary_map']['interface']['occ_surface_tags']), 1)
            self.assertEqual(len(manifest['boundary_map']['outerWalls']['occ_surface_tags']), 5)
            geo = (Path(tmp) / 'geometry' / 'coupled.geo').read_text()
            for name in ('inlet', 'outlet', 'heated', 'outerWalls', 'fluid', 'solid'):
                self.assertIn(f'"{name}"', geo)
            audit = json.loads((Path(tmp) / 'geometry' / 'manifest.json').read_text())
            self.assertEqual(audit['checks']['source_immutable'], 'pass')

    def test_wrong_port_selection_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            handoff = synthetic_handoff(Path(tmp) / 'handoff')
            path = handoff / 'requirements.json'
            requirements = json.loads(path.read_text())
            requirements['selections']['outlet'] = requirements['selections']['inlet']
            path.write_text(json.dumps(requirements))
            with self.assertRaises(ValueError):
                extract(handoff, Path(tmp) / 'geometry')


if __name__ == '__main__':
    unittest.main()
