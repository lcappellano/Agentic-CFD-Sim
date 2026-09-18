"""Read-only viewer guards on synthetic exports."""
import json
from pathlib import Path
import tempfile
import unittest

from src.results import export


class ExportGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='results-guard-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = {'case_name': 'cases/x', 'time': '10', 'provenance': {'input_sha256': {}}}
        self.write()

    def write(self, sources=None):
        sources = {} if sources is None else sources
        self.data['provenance']['input_sha256'] = sources
        (self.folder / 'results.json').write_text(json.dumps(self.data))
        (self.folder / 'summary.json').write_text('{}')
        manifest = {'schema_version': 1, 'export_kind': 'saved_case_v1', 'case_name': 'cases/x', 'time': '10',
                    'summary_sha256': export.digest(self.folder / 'summary.json'),
                    'files': {'results.json': export.digest(self.folder / 'results.json')}, 'input_sha256': sources}
        (self.folder / 'manifest.json').write_text(json.dumps(manifest))

    def test_payload_modification_rejected(self):
        export.verify_export(self.folder)
        (self.folder / 'results.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            export.verify_export(self.folder)

    def test_escape_source_paths_rejected(self):
        for name in ('../secret', '/etc/passwd'):
            self.write({name: '0' * 64})
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, 'Unsafe'):
                export.verify_export(self.folder)

    def test_stale_source_rejected(self):
        (self.folder / 'field').write_text('changed field')
        self.write({'field': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'Stale export source'):
            export.verify_export(self.folder, self.folder)

    def test_nonfinite_payload_rejected(self):
        self.data['invalid'] = float('nan')
        self.write()
        with self.assertRaisesRegex(ValueError, 'Nonfinite'):
            export.verify_export(self.folder)


if __name__ == '__main__':
    unittest.main()
