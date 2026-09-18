"""Loopback-only STEP review UI; serves local assets and explicit user actions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from . import review

WEB = Path(__file__).resolve().parent / 'web'


def make_server(folder, port=8765):
    folder = Path(folder).resolve()
    review.read_state(folder)  # Fail before listening if snapshots are invalid.
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def send_data(self, code, data, content_type='application/json'):
            if not isinstance(data, bytes):
                data = json.dumps(data, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def local_request(self):
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            if host not in allowed or (origin is not None and origin not in {'http://' + x for x in allowed}):
                self.send_data(403, {'error': 'Use the local review URL directly.'})
                return False
            return True

        def get_state(self):
            return {**review.read_state(folder), 'csrf_token': token}

        def do_GET(self):
            if not self.local_request():
                return
            route = urlsplit(self.path).path
            try:
                if route == '/api/state':
                    self.send_data(200, self.get_state())
                    return
                if route == '/':
                    path = WEB / 'index.html'
                elif route in ('/app.js', '/style.css'):
                    path = WEB / route[1:]
                elif route in ('/vendor/three.module.js', '/vendor/three.core.js', '/vendor/OrbitControls.js', '/vendor/ArcballControls.js'):
                    path = WEB / route[1:]
                else:
                    self.send_data(404, {'error': 'Not found.'})
                    return
                self.send_data(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            except review.ConflictError as error:
                self.send_data(409, {'error': str(error)})
            except (ValueError, OSError, KeyError) as error:
                self.send_data(400, {'error': str(error)})

        def do_POST(self):
            if not self.local_request():
                return
            if not secrets.compare_digest(self.headers.get('X-Review-Token', ''), token):
                self.send_data(403, {'error': 'Reload the review page before saving or confirming.'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Request must be a JSON object.')
                route = urlsplit(self.path).path
                if route == '/api/draft':
                    state = review.save_draft(folder, data['draft'], data['expected_revision'])
                elif route == '/api/approve':
                    state = review.approve(folder, data['expected_revision'], data['draft_sha256'],
                                           data.get('confirmed'), data.get('reviewer'))
                elif route == '/api/handoff':
                    self.send_data(200, review.handoff(folder))
                    return
                else:
                    self.send_data(404, {'error': 'Not found.'})
                    return
                self.send_data(200, {**state, 'csrf_token': token})
            except review.ConflictError as error:
                self.send_data(409, {'error': str(error)})
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.send_data(400, {'error': str(error)})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def serve(folder, port=8765):
    server = make_server(folder, port)
    print(f'Requirements viewer: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Review folder: {Path(folder).resolve()}', flush=True)
    print('Review only. Stop with Ctrl+C. No simulation will launch.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
