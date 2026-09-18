"""Read-only viewer guards and independent saved-field/export comparisons."""
from http.client import HTTPConnection
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.results import export
from src.verification.audit_demo_fields import patch, values


class ExportGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='results-guard-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = {'case_name': export.CASE, 'time': export.TIME,
                     'provenance': {'input_sha256': {}}}
        self.write()

    def write(self, sources=None):
        sources = {} if sources is None else sources
        self.data['provenance']['input_sha256'] = sources
        (self.folder/'results.json').write_text(json.dumps(self.data))
        manifest = {'schema_version': 1, 'files': {'results.json': export.digest(self.folder/'results.json')},
                    'input_sha256': sources}
        (self.folder/'manifest.json').write_text(json.dumps(manifest))

    def test_payload_modification_rejected(self):
        export.verify_export(self.folder)
        (self.folder/'results.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            export.verify_export(self.folder)

    def test_escape_source_paths_rejected(self):
        for name in ('../secret', '/etc/passwd'):
            self.write({name: '0'*64})
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, 'Unsafe'):
                export.verify_export(self.folder)

    def test_rejected_case_cannot_be_displayed_as_accepted(self):
        self.data['case_name'] = 'case-fine-final'
        self.write()
        with self.assertRaisesRegex(ValueError, 'case/time'):
            export.verify_export(self.folder)

    def test_stale_source_rejected(self):
        (self.folder/'field').write_text('changed field')
        self.write({'field': '0'*64})
        with self.assertRaisesRegex(ValueError, 'Stale export source'):
            export.verify_export(self.folder, self.folder)

    def test_nonfinite_payload_rejected(self):
        self.data['invalid'] = float('nan')
        self.write()
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            export.verify_export(self.folder)


@unittest.skipUnless(os.environ.get('WORKBENCH_RESULTS_EXPORT'), 'Set WORKBENCH_RESULTS_EXPORT for actual saved-field tests')
class ActualResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(os.environ['WORKBENCH_RESULTS_EXPORT']).resolve()
        cls.source_run = Path(os.environ['WORKBENCH_RESULTS_RUN']).resolve()
        cls.data = json.loads((cls.folder/'results.json').read_text())
        cls.case = cls.source_run/export.CASE

    def test_source_hashes_and_acceptance(self):
        export.verify_export(self.folder, self.source_run)
        self.assertEqual(self.data['acceptance']['numerical_criteria'], 'pass')
        self.assertEqual(self.data['acceptance']['experimental_validation'], 'not checked')
        self.assertEqual(self.data['temperature_limit_K'], 500)
        self.assertEqual(self.data['pressure_reference_Pa'], 101325)

    def test_every_boundary_triangle_matches_independent_raw_reader(self):
        for surface in self.data['surfaces']:
            region, name = surface['region'], surface['patch']
            count = len(surface['cell_ids'])
            self.assertEqual(len(surface['positions_mm']), count*9)
            boundary = (self.case/'constant'/region/'polyMesh/boundary').read_text()
            import re
            block = re.search(r'\b'+name+r'\s*\{([^{}]+)\}', boundary)[1]
            start = int(re.search(r'startFace\s+(\d+)', block)[1])
            for field in ('T',) if region == 'solid' else ('T', 'p', 'U'):
                raw_text = (self.case/export.TIME/region/field).read_text()
                raw_block = re.search(r'\b'+name+r'\s*\{([^{}]+)\}', raw_text)[1]
                if field == 'U' and re.search(r'\btype\s+noSlip\s*;', raw_block):
                    raw = [(0.0,0.0,0.0)] * int(re.search(r'nFaces\s+(\d+)', block)[1])
                else:
                    raw = patch(self.case, export.TIME, region, field, name)
                self.assertEqual(len(surface['values'][field]), count)
                for face, value in zip(surface['face_ids'], surface['values'][field]):
                    expected = raw[face-start]
                    self.assertEqual(value, list(expected) if isinstance(expected, tuple) else expected)
        heated = next(s for s in self.data['surfaces'] if s['id']=='solid:heated')
        self.assertAlmostEqual(max(heated['values']['T']), 308.2517476696, places=7)

    def test_all_slice_values_and_plane_coordinates(self):
        raw = {}
        for name in ('T','p','U'):
            content = (self.case/export.TIME/'fluid'/name).read_text()
            raw[name] = values(content.split('internalField',1)[1].split('boundaryField',1)[0])
        self.assertEqual(len(self.data['slices']),9)
        for cut in self.data['slices']:
            axis = 'xyz'.index(cut['axis'])
            for coordinate in cut['positions_mm'][axis::3]:
                self.assertAlmostEqual(coordinate,cut['position_mm'],places=7)
            for index,cell in enumerate(cut['cell_ids']):
                for name, field in raw.items():
                    expected=field[0] if len(field)==1 else field[cell]
                    self.assertEqual(cut['values'][name][index],list(expected) if isinstance(expected,tuple) else expected)
                self.assertAlmostEqual(cut['values']['speed'][index], math.sqrt(sum(x*x for x in cut['values']['U'][index])))

    def test_readonly_server_and_path_guards(self):
        from src.results.server import make_server
        server=make_server(self.folder,port=0,run=self.source_run)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            def request(method,path,headers=None):
                conn=HTTPConnection('127.0.0.1',server.server_port)
                conn.request(method,path,headers=headers or {})
                response=conn.getresponse(); body=response.read(); status=response.status
                conn.close()
                return status,body
            self.assertEqual(request('GET','/api/results')[0],200)
            self.assertEqual(request('GET','/api/meta')[0],200)
            for method in ('POST','PUT','DELETE','PATCH'):
                self.assertEqual(request(method,'/api/results')[0],405)
            for path in ('/../project.json','/%2e%2e/project.json','/manifest.json','/.git/config','/api/results/../../project.json'):
                self.assertIn(request('GET',path)[0],(400,403,404))
            self.assertIn(request('GET','/api/results',{'Host':'attacker.example'})[0],(400,403))
            self.assertIn(request('GET','/api/results',{'Origin':'https://attacker.example'})[0],(400,403))
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
