"""Synthetic smooth-tube benchmark part: generation, handoff selections, spec resolution; mesh e2e."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from src.pipeline import spec as spec_module
from src.pipeline.benchmarks import smooth_tube_handoff, volume_flow_for_reynolds

ROOT = Path(__file__).resolve().parents[2]


class SmoothTubeTests(unittest.TestCase):
    def test_handoff_has_two_bore_ports_and_the_top_face_heated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = smooth_tube_handoff(root / 'handoff', bore_mm=2.0, length_mm=40.0, block_mm=8.0)
            req = json.loads((handoff / 'requirements.json').read_text())
            model = json.loads((handoff / 'model.json').read_text())
            self.assertEqual(model['solid_count'], 1)
            ports = {v['id']: v for v in model['virtual_faces']}
            inlet, outlet = req['selections']['inlet'][0], req['selections']['outlet'][0]
            self.assertAlmostEqual(ports[inlet]['centroid_mm'][0], 0.0, places=5)
            self.assertAlmostEqual(ports[outlet]['centroid_mm'][0], 40.0, places=5)
            self.assertAlmostEqual(ports[inlet]['radius_mm'], 1.0, places=5)
            heated = next(f for f in model['faces'] if f['id'] == req['selections']['heated'][0])
            self.assertAlmostEqual(heated['centroid_mm'][2], 8.0, places=5)
            self.assertAlmostEqual(heated['area_mm2'], 320.0, places=3)
            self.assertIn('not a user approval', req['requirements']['notes'])
            record = json.loads((handoff / 'benchmark.json').read_text())
            self.assertEqual(record['length_over_diameter'], 20.0)
            spec = {'schema_version': 1, 'handoff': 'handoff', 'unapproved_handoff_ok': True,
                    'operating': {'volume_flow_L_min': 2.46, 'inlet_temperature_C': 20}}
            (root / 'spec.json').write_text(json.dumps(spec))
            resolved = spec_module.resolve(spec_module.load(root / 'spec.json'), root)
            self.assertEqual(resolved['operating']['outlet_absolute_pressure_Pa'], 800000.0)
            self.assertEqual(resolved['operating']['heat_flux_W_m2'], 1e6)

    def test_volume_flow_for_reynolds(self):
        q = volume_flow_for_reynolds(26000, 0.002, 998.2, 1.0016e-3)
        self.assertAlmostEqual(q * 60000, 2.457, places=2)  # L/min


@unittest.skipUnless(os.environ.get('WORKBENCH_E2E'), 'set WORKBENCH_E2E=1 to run the mesher')
class SmoothTubeEndToEnd(unittest.TestCase):
    def test_tube_extracts_and_meshes(self):
        from src.pipeline.driver import simulate
        root = ROOT / 'runs' / '_e2e_tube'
        if root.exists():
            shutil.rmtree(root)
        (root / 'runs').mkdir(parents=True)
        smooth_tube_handoff(root / 'handoff', bore_mm=2.0, length_mm=20.0, block_mm=6.0)
        spec = {'schema_version': 1, 'handoff': 'handoff', 'label': 'e2e-tube', 'unapproved_handoff_ok': True,
                'operating': {'volume_flow_L_min': 2.46, 'inlet_temperature_C': 20}, 'mesh': {'profile': 'tet-test'},
                'acceptance': {'profile': 'test-loose'}}
        (root / 'spec.json').write_text(json.dumps(spec))
        state = simulate(root, root / 'spec.json', until='mesh', log=lambda *_: None)
        self.assertEqual(state['status'], 'stopped_after_mesh', state['stages'])
        self.assertAlmostEqual(float(state['stages']['geometry']['summary']['fluid_m3']), 3.1416e-6 * 0.02 * 0.001 / 0.001, delta=2e-9)
        shutil.rmtree(root)


if __name__ == '__main__':
    unittest.main()
