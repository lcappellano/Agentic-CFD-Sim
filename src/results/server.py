"""Read-only loopback viewer for verified, frozen simulation-result exports."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from .export import verify_export

WEB = Path(__file__).resolve().parent / 'web'
VENDOR = Path(__file__).resolve().parents[1] / 'requirements/web/vendor'


def make_server(folder, port=8766, run=None):
    folder = Path(folder).resolve()
    source_run = Path(run).resolve() if run is not None else folder.parents[1]
    verify_export(folder, source_run)  # Fail before opening the viewer on stale fields.

    def checked_payload():
        manifest = verify_export(folder, source_run)
        data = (folder / 'results.json').read_bytes()
        # The exporter checks this too; compare the actual bytes sent to avoid a
        # changed payload being served between verification and reading.
        expected = manifest.get('results_sha256', manifest.get('payload_sha256'))
        if expected is None:
            expected = manifest.get('files', {}).get('results.json')
        if expected is None or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Results payload changed; export the accepted results again.')
        return manifest, data

    class Handler(BaseHTTPRequestHandler):
        def send_data(self, code, data, content_type='application/json'):
            if not isinstance(data, bytes):
                data = json.dumps(data, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def local_request(self):
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            if self.headers.get('Host') not in hosts or (origin is not None and origin not in {'http://' + host for host in hosts}):
                self.send_data(403, {'error': 'Open the local results viewer URL directly.'})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            route = urlsplit(self.path).path
            try:
                if route in ('/api/results', '/api/meta'):
                    manifest, payload = checked_payload()
                    if route == '/api/results':
                        self.send_data(200, payload)
                    else:
                        data = json.loads(payload)
                        self.send_data(200, {key: data[key] for key in ('schema_version', 'run_id', 'case_name', 'time', 'acceptance', 'summary') if key in data})
                    return
                if route == '/':
                    path = WEB / 'index.html'
                elif route in ('/app.js', '/style.css'):
                    path = WEB / route[1:]
                elif route in ('/vendor/three.module.js', '/vendor/three.core.js', '/vendor/OrbitControls.js', '/vendor/ArcballControls.js'):
                    path = VENDOR / route.rsplit('/', 1)[1]
                elif route in ('/report', '/report/temperature.png', '/report/convergence.png'):
                    verify_export(folder, source_run)
                    names = {'/report': 'report.md', '/report/temperature.png': 'surface-temperature.png', '/report/convergence.png': 'convergence.png'}
                    path = source_run / 'report' / names[route]
                else:
                    self.send_data(404, {'error': 'Not found.'})
                    return
                if not path.is_file():
                    self.send_data(404, {'error': 'This artifact is unavailable.'})
                    return
                content_type = 'text/plain; charset=utf-8' if path.suffix == '.md' else mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                self.send_data(200, path.read_bytes(), content_type)
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.send_data(409, {'error': f'Results validation failed: {error}'})

        def reject_write(self):
            if self.local_request():
                self.send_data(405, {'error': 'This results viewer is read-only.'})

        do_POST = reject_write
        do_PUT = reject_write
        do_PATCH = reject_write
        do_DELETE = reject_write

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(folder, port=8766, run=None):
    server = make_server(folder, port, run)
    print(f'Results viewer: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Export: {Path(folder).resolve()}', flush=True)
    print('Read-only saved simulation results. Stop with Ctrl+C.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
