"""Export the verified fixed-demo ASCII OpenFOAM fields for a read-only viewer.

No solver or interpolation is run. Each triangle retains its source face/cell and
one saved field value. Interior cuts are convex cell/plane intersections, colored
with piecewise-constant cell values (not reconstructed nodal values).
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from src.cfd.summarize_demo import mesh_list, read_boundary
from src.verification.audit_demo_fields import values

CASE = 'case-hex-fine-corrected'
TIME = '2000'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path):
    return json.loads(path.read_text(), parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+s)))


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite export value')
    if isinstance(value, dict):
        for v in value.values(): finite(v)
    elif isinstance(value, (tuple, list)):
        for v in value: finite(v)


def resolve_record(run, recorded):
    """Resolve historical absolute/workspace paths inside this portable run only."""
    parts = Path(recorded).parts
    if run.name in parts:
        relative = Path(*parts[parts.index(run.name)+1:])
    else:
        relative = Path(recorded)
    path = (run / relative).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError('Evidence path outside run: '+recorded)
    return path


def verify_inputs(run):
    decision = load_json(run/'verification-decision.json')
    if decision.get('status') != 'accepted_with_model_limits' or decision.get('numerical_criteria') != 'pass':
        raise ValueError('Expected accepted fixed-demo verification decision')
    hashes = {}
    for recorded, expected in decision['evidence_sha256'].items():
        path = resolve_record(run, recorded)
        if digest(path) != expected: raise ValueError('Stale decision evidence: '+recorded)
        hashes[path.relative_to(run).as_posix()] = expected
    evidence = load_json(run/'verification-final-evidence.json')
    if not evidence.get('numerical_checks_pass'): raise ValueError('Numerical evidence did not pass')
    for recorded, expected in evidence['input_sha256'].items():
        path = resolve_record(run, recorded)
        if digest(path) != expected: raise ValueError('Stale verified input: '+recorded)
        hashes[path.relative_to(run).as_posix()] = expected
    summary = evidence['cases'][CASE]['summary']
    if summary['latest_fields'] != TIME: raise ValueError('Unexpected accepted field time')
    times = [p.name for p in (run/CASE).iterdir() if p.is_dir() and re.fullmatch(r'\d+(?:\.\d+)?', p.name)]
    if max(times, key=float) != TIME: raise ValueError('Newer fields require renewed verification')
    return decision, summary, hashes


def read_mesh(mesh):
    points = [tuple(map(float, p.split())) for p in re.findall(r'\(([^()]+)\)', mesh_list(mesh/'points'))]
    faces = [tuple(map(int, f.split())) for f in re.findall(r'\d+\(([^()]+)\)', mesh_list(mesh/'faces'))]
    owner = list(map(int, mesh_list(mesh/'owner').split()))
    neighbour = list(map(int, mesh_list(mesh/'neighbour').split()))
    patches = {}
    for name, block in re.findall(r'(\w+)\s*\{([^{}]+)\}', mesh_list(mesh/'boundary')):
        n = re.search(r'nFaces\s+(\d+)', block)
        start = re.search(r'startFace\s+(\d+)', block)
        if n and start: patches[name] = (int(start[1]), int(n[1]))
    if len(owner) != len(faces): raise ValueError('Mesh owner/face mismatch')
    finite(points)
    return points, faces, owner, neighbour, patches


def read_internal(path, count, dimensions):
    text = path.read_text()
    if not re.search(r'format\s+ascii\s*;', text): raise ValueError('Only ASCII fields are supported')
    dims = re.search(r'dimensions\s*\[([^\]]+)\]', text)
    if not dims or list(map(float, dims[1].split())) != dimensions:
        raise ValueError('Unexpected field dimensions: '+str(path))
    data = values(text.split('internalField', 1)[1].split('boundaryField', 1)[0])
    if len(data) == 1: data *= count
    if len(data) != count: raise ValueError('Internal field cell count mismatch')
    finite(data)
    return data


def empty_mesh(identifier, region, fields, **extra):
    return dict(id=identifier, region=region, positions_mm=[], cell_ids=[], face_ids=[],
                values={key: [] for key in fields}, **extra)


def add_polygon(out, polygon, cell_id, sample, face_id=None):
    for i in range(1, len(polygon)-1):
        for point in (polygon[0], polygon[i], polygon[i+1]):
            out['positions_mm'].extend(round(x*1000, 10) for x in point)
        out['cell_ids'].append(cell_id)
        if face_id is not None: out['face_ids'].append(face_id)
        for name, value in sample.items(): out['values'][name].append(value)


def cell_slices(points, faces, owner, neighbour, internal):
    count = len(internal['T'])
    cell_faces = [[] for _ in range(count)]
    for index, cell in enumerate(owner): cell_faces[cell].append(index)
    for index, cell in enumerate(neighbour): cell_faces[cell].append(index)
    bounds = [[min(p[a] for p in points) for a in range(3)], [max(p[a] for p in points) for a in range(3)]]
    cuts = []
    for axis in range(3):
        for fraction in (.25, .5, .75):
            position = bounds[0][axis]+fraction*(bounds[1][axis]-bounds[0][axis])
            cuts.append((axis, position, empty_mesh(f'fluid:slice:{"xyz"[axis]}:{fraction}', 'fluid', internal,
                axis='xyz'[axis], position_mm=position*1000, sampling='piecewise constant saved cell values')))
    for cell, face_ids in enumerate(cell_faces):
        edges = set()
        nodes = set()
        for face_id in face_ids:
            face = faces[face_id]; nodes.update(face)
            for i, a in enumerate(face): edges.add(tuple(sorted((a, face[(i+1)%len(face)]))))
        if len(nodes) != 8: raise ValueError('Interior cuts currently require the verified convex hex demo mesh')
        low = [min(points[n][a] for n in nodes) for a in range(3)]
        high = [max(points[n][a] for n in nodes) for a in range(3)]
        for axis, position, out in cuts:
            # Half-open selection prevents doubled faces at cell-aligned cuts.
            if not low[axis]-1e-12 <= position < high[axis]-1e-12: continue
            hits = {}
            for a, b in edges:
                p, q = points[a], points[b]
                if abs(p[axis]-position) <= 1e-12: hits[tuple(round(v, 12) for v in p)] = p
                if abs(q[axis]-position) <= 1e-12: hits[tuple(round(v, 12) for v in q)] = q
                if (p[axis]-position)*(q[axis]-position) < 0:
                    t = (position-p[axis])/(q[axis]-p[axis])
                    point = tuple(p[a]+t*(q[a]-p[a]) for a in range(3))
                    hits[tuple(round(v, 12) for v in point)] = point
            polygon = list(hits.values())
            if len(polygon) < 3: continue
            axes = [a for a in range(3) if a != axis]
            centre = [sum(p[a] for p in polygon)/len(polygon) for a in range(3)]
            polygon.sort(key=lambda p: math.atan2(p[axes[1]]-centre[axes[1]], p[axes[0]]-centre[axes[0]]))
            add_polygon(out, polygon, cell, {name: data[cell] for name, data in internal.items()})
    return [out for _, _, out in cuts]


def export_results(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('Export destination already exists; use a new versioned directory')
    decision, summary, hashes = verify_inputs(run)
    case = run/CASE
    surfaces, slices, all_points = [], [], []
    dimensions = {'T':[0,0,0,1,0,0,0], 'p':[1,-1,-2,0,0,0,0], 'U':[0,1,-1,0,0,0,0]}
    for region in ('solid', 'fluid'):
        mesh = case/'constant'/region/'polyMesh'
        points, faces, owner, neighbour, patches = read_mesh(mesh)
        all_points.extend(points)
        fields = ['T'] if region == 'solid' else ['T','p','U']
        count = max(owner+neighbour)+1
        internal = {name:read_internal(case/TIME/region/name, count, dimensions[name]) for name in fields}
        if region == 'fluid': internal['speed'] = [math.sqrt(sum(v*v for v in u)) for u in internal['U']]
        for patch, (start, size) in patches.items():
            if not size: continue
            samples = {}
            for name in fields:
                path = case/TIME/region/name
                block = re.search(r'\b'+re.escape(patch)+r'\s*\{([^{}]+)\}', path.read_text(), re.S)
                if name == 'U' and block and re.search(r'type\s+noSlip\s*;', block[1]):
                    samples[name] = [(0., 0., 0.)]*size  # Exact saved noSlip condition.
                else:
                    samples[name] = read_boundary(path, patch, mesh)
            finite(samples)
            if region == 'fluid': samples['speed'] = [math.sqrt(sum(v*v for v in u)) for u in samples['U']]
            out = empty_mesh(region+':'+patch, region, samples, patch=patch, sampling='saved boundary face values')
            for j, face_id in enumerate(range(start, start+size)):
                add_polygon(out, [points[n] for n in faces[face_id]], owner[face_id],
                            {name:data[j] for name,data in samples.items()}, face_id)
            surfaces.append(out)
        if region == 'fluid': slices = cell_slices(points, faces, owner, neighbour, internal)
        for path in [mesh/n for n in ('points','faces','owner','neighbour','boundary')]+[case/TIME/region/n for n in fields]:
            hashes[path.relative_to(run).as_posix()] = digest(path)
    project = load_json(run/'resolved-project.json')
    reference = project.get('pressure_input', {}).get('reference_pressure_Pa')
    if reference is None:
        settings = load_json(run/'baseline-settings.json')
        reference = settings['reference_absolute_pressure_Pa']
    for name in ('verification-decision.json','resolved-project.json','baseline-settings.json'):
        hashes[name] = digest(run/name)
    result = dict(schema_version=1, exported_at=datetime.now(timezone.utc).isoformat(), run_id=run.name, case_name=CASE, time=TIME,
                  coordinate_units='mm', field_association='triangle',
                  fields={'T':{'units':'K'}, 'p':{'units':'Pa','reference':'absolute'},
                          'U':{'units':'m/s','components':3}, 'speed':{'units':'m/s'}},
                  bounds_mm=[[min(p[a] for p in all_points)*1000 for a in range(3)],
                             [max(p[a] for p in all_points)*1000 for a in range(3)]],
                  surfaces=surfaces, slices=slices, summary=summary, acceptance=decision,
                  temperature_limit_K=project['maximum_surface_temperature_K'],
                  pressure_reference_Pa=reference,
                  limitations=['Steady saved solution; not a transient animation.',
                               'Slices use piecewise constant cell values; surface colors use boundary face values.',
                               'Fixed demo only; paired mesh sensitivity is not formal grid independence.', decision['qualification']],
                  provenance={'input_sha256':hashes, 'solver':'OpenCFD OpenFOAM v2412 chtMultiRegionSimpleFoam',
                              'exporter_sha256':digest(Path(__file__)), 'pressure_definition':'Absolute static pressure in Pa; g=0.'})
    # Check again after reading to avoid accepting a changing result directory.
    for relative, expected in hashes.items():
        if digest(run/relative) != expected: raise ValueError('Input changed during export: '+relative)
    finite(result)
    output.mkdir(parents=True)
    path = output/'results.json'
    path.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n')
    manifest = dict(schema_version=1, run_id=run.name, case_name=CASE, time=TIME,
                    files={'results.json':digest(path)}, input_sha256=hashes,
                    exporter_sha256=digest(Path(__file__)), frozen=True)
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return path


def verify_export(output, run=None):
    """Verify frozen payload, optionally all original input hashes in a moved run."""
    output = Path(output).resolve()
    manifest = load_json(output/'manifest.json')
    if manifest.get('schema_version') != 1 or manifest.get('files', {}).keys() != {'results.json'}:
        raise ValueError('Unsupported export manifest')
    if digest(output/'results.json') != manifest['files']['results.json']:
        raise ValueError('Export payload hash mismatch')
    for relative in manifest['input_sha256']:
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe source path in export manifest')
    data = load_json(output/'results.json')
    if data.get('case_name') != CASE or data.get('time') != TIME:
        raise ValueError('Unsupported exported case/time')
    if data['provenance']['input_sha256'] != manifest['input_sha256']:
        raise ValueError('Payload and manifest provenance differ')
    if run is not None:
        run = Path(run).resolve()
        for relative, expected in manifest['input_sha256'].items():
            path = (run/relative).resolve()
            if not path.is_relative_to(run) or digest(path) != expected:
                raise ValueError('Stale export source: '+relative)
        verify_inputs(run)
    finite(data)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(export_results(args.run, args.output))
