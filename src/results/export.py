"""Freeze saved ASCII fields into a viewer payload with per-triangle values.

No solver or interpolation runs. Boundary triangles carry saved face values;
interior cuts are convex cell/plane intersections coloured with saved cell values.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from src.foam.fields import PolyMesh, field_dimensions
from src.foam.hashing import digest

DIMENSIONS = {'T': [0, 0, 0, 1, 0, 0, 0], 'p': [1, -1, -2, 0, 0, 0, 0], 'U': [0, 1, -1, 0, 0, 0, 0]}


def load_json(path):
    def reject(token):
        raise ValueError('Nonfinite JSON: ' + token)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite export value')
    if isinstance(value, dict):
        for v in value.values():
            finite(v)
    elif isinstance(value, (tuple, list)):
        for v in value:
            finite(v)


def empty_mesh(identifier, region, fields, **extra):
    return dict(id=identifier, region=region, positions_mm=[], cell_ids=[], face_ids=[],
                values={key: [] for key in fields}, **extra)


def add_polygon(out, polygon, cell_id, sample, face_id=None):
    for i in range(1, len(polygon) - 1):
        for point in (polygon[0], polygon[i], polygon[i + 1]):
            out['positions_mm'].extend(round(x * 1000, 10) for x in point)
        out['cell_ids'].append(cell_id)
        if face_id is not None:
            out['face_ids'].append(face_id)
        for name, value in sample.items():
            out['values'][name].append(value)


def cell_slices(points, faces, owner, neighbour, internal, allowed_nodes=(8,)):
    count = len(internal['T'])
    cell_faces = [[] for _ in range(count)]
    for index, cell in enumerate(owner):
        cell_faces[cell].append(index)
    for index, cell in enumerate(neighbour):
        cell_faces[cell].append(index)
    bounds = [[min(p[a] for p in points) for a in range(3)], [max(p[a] for p in points) for a in range(3)]]
    cuts = []
    for axis in range(3):
        for fraction in (.25, .5, .75):
            position = bounds[0][axis] + fraction * (bounds[1][axis] - bounds[0][axis])
            cuts.append((axis, position, empty_mesh(f'fluid:slice:{"xyz"[axis]}:{fraction}', 'fluid', internal,
                                                    axis='xyz'[axis], position_mm=position * 1000,
                                                    sampling='piecewise constant saved cell values')))
    for cell, face_ids in enumerate(cell_faces):
        edges, nodes = set(), set()
        for face_id in face_ids:
            face = faces[face_id]
            nodes.update(face)
            for i, a in enumerate(face):
                edges.add(tuple(sorted((a, face[(i + 1) % len(face)]))))
        if len(nodes) not in allowed_nodes:
            raise ValueError('Unsupported cell topology for convex plane cuts')
        low = [min(points[n][a] for n in nodes) for a in range(3)]
        high = [max(points[n][a] for n in nodes) for a in range(3)]
        for axis, position, out in cuts:
            if not low[axis] - 1e-12 <= position < high[axis] - 1e-12:
                continue
            hits = {}
            for a, b in edges:
                p, q = points[a], points[b]
                if abs(p[axis] - position) <= 1e-12:
                    hits[tuple(round(v, 12) for v in p)] = p
                if abs(q[axis] - position) <= 1e-12:
                    hits[tuple(round(v, 12) for v in q)] = q
                if (p[axis] - position) * (q[axis] - position) < 0:
                    t = (position - p[axis]) / (q[axis] - p[axis])
                    point = tuple(p[a] + t * (q[a] - p[a]) for a in range(3))
                    hits[tuple(round(v, 12) for v in point)] = point
            polygon = list(hits.values())
            if len(polygon) < 3:
                continue
            axes = [a for a in range(3) if a != axis]
            centre = [sum(p[a] for p in polygon) / len(polygon) for a in range(3)]
            polygon.sort(key=lambda p: math.atan2(p[axes[1]] - centre[axes[1]], p[axes[0]] - centre[axes[0]]))
            add_polygon(out, polygon, cell, {name: data[cell] for name, data in internal.items()})
    return [out for _, _, out in cuts]


def collect_fields(run, case, time, hashes, allowed_nodes=(4, 8)):
    surfaces, slices, all_points, extrema = [], [], [], {}
    for region in ('solid', 'fluid'):
        mesh = PolyMesh(case / 'constant' / region / 'polyMesh')
        all_points.extend(mesh.points)
        fields = ['T'] if region == 'solid' else ['T', 'p', 'U']
        internal = {}
        for name in fields:
            path = case / time / region / name
            if field_dimensions(path) != DIMENSIONS[name]:
                raise ValueError('Unexpected field dimensions: ' + str(path))
            if not re.search(r'format\s+ascii\s*;', path.read_text()):
                raise ValueError('Only ASCII fields are supported')
            internal[name] = mesh.read_internal(path)
        extrema[region] = {'internal_min': min(internal['T']), 'internal_max': max(internal['T']),
                           'min': min(internal['T']), 'max': max(internal['T'])}
        if region == 'fluid':
            internal['speed'] = [math.sqrt(sum(v * v for v in u)) for u in internal['U']]
        for patch, (start, size) in mesh.patches.items():
            if not size:
                continue
            samples = {name: mesh.read_boundary(case / time / region / name, patch) for name in fields}
            finite(samples)
            extrema[region]['min'] = min(extrema[region]['min'], min(samples['T']))
            extrema[region]['max'] = max(extrema[region]['max'], max(samples['T']))
            if region == 'fluid':
                samples['speed'] = [math.sqrt(sum(v * v for v in u)) for u in samples['U']]
            out = empty_mesh(region + ':' + patch, region, samples, patch=patch, sampling='saved boundary face values')
            for j, face_id in enumerate(range(start, start + size)):
                add_polygon(out, [mesh.points[n] for n in mesh.faces[face_id]], mesh.owner[face_id],
                            {name: data[j] for name, data in samples.items()}, face_id)
            surfaces.append(out)
        if region == 'fluid':
            slices = cell_slices(mesh.points, mesh.faces, mesh.owner, mesh.neighbour, internal, allowed_nodes)
        for path in [mesh.folder / n for n in ('points', 'faces', 'owner', 'neighbour', 'boundary')] + [case / time / region / n for n in fields]:
            hashes[path.relative_to(run).as_posix()] = digest(path)
    return surfaces, slices, all_points, extrema


def verify_export(output, run=None):
    """Verify a frozen payload and, given the run, every recorded source hash."""
    output = Path(output).resolve()
    manifest = load_json(output / 'manifest.json')
    if manifest.get('schema_version') != 1 or manifest.get('files', {}).keys() != {'results.json'}:
        raise ValueError('Unsupported export manifest')
    if digest(output / 'results.json') != manifest['files']['results.json']:
        raise ValueError('Export payload hash mismatch')
    for relative in manifest['input_sha256']:
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe source path in export manifest')
    data = load_json(output / 'results.json')
    if manifest.get('export_kind') != 'saved_case_v1':
        raise ValueError('Unsupported export kind')
    if digest(output / 'summary.json') != manifest.get('summary_sha256'):
        raise ValueError('Saved summary hash mismatch')
    if any(data.get(k) != manifest.get(k) for k in ('case_name', 'time')):
        raise ValueError('Saved case identity mismatch')
    if data['provenance']['input_sha256'] != manifest['input_sha256']:
        raise ValueError('Payload and manifest provenance differ')
    if run is not None:
        run = Path(run).resolve()
        for relative, expected in manifest['input_sha256'].items():
            path = (run / relative).resolve()
            if not path.is_relative_to(run) or digest(path) != expected:
                raise ValueError('Stale export source: ' + relative)
        from src.results.saved_case import verify_saved_inputs
        decision, _, _ = verify_saved_inputs(run, data['case_name'], data['time'])
        if decision != data['acceptance']:
            raise ValueError('Saved result status changed')
    finite(data)
    return manifest


def now():
    return datetime.now(timezone.utc).isoformat()
