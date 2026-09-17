"""Request intake and immutable-by-convention run snapshots; never runs a solver."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import uuid


STAGES = [
    ('intake', 'manager', 'Resolve requirements and assumptions.'),
    ('requirements_review', 'requirements + user', 'Visually confirm exact ports, heated surfaces and physical requirements before CAD handoff.'),
    ('geometry', 'cad', 'Verify regions, interfaces and boundary identities.'),
    ('estimates', 'thermal', 'Check loads and select a bounded baseline.'),
    ('baseline', 'cfd', 'Build and execute one recorded CHT case.'),
    ('review', 'verification', 'Review conservation, convergence and mesh evidence.'),
    ('sweep', 'cfd + thermal', 'Only after baseline review; fixed geometry first.'),
    ('report', 'manager', 'Integrate reviewed evidence and unresolved limits.'),
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def local_path(root, value):
    path = (root / value).resolve()
    path.relative_to(root.resolve())
    return path


def read_spec(root, name):
    path = local_path(root, name)
    raw = path.read_bytes()
    spec = json.loads(raw)
    if not isinstance(spec, dict):
        raise ValueError('Project specification must be a JSON object.')
    return path, raw, spec


def positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def check_spec(root, spec):
    issues = []
    version = spec.get('schema_version')
    if type(version) is not int or version not in (1, 2):
        issues.append('schema_version must be 1 or 2.')
    cad = spec.get('cad_file')
    try:
        if not isinstance(cad, str) or not cad.strip() or not local_path(root, cad).is_file():
            issues.append('cad_file: provide an existing file inside the workspace.')
    except ValueError:
        issues.append('cad_file must stay inside the workspace.')
    for name in ('heated_faces', 'inlet_faces', 'outlet_faces'):
        value = spec.get(name)
        if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            issues.append(f'{name}: provide nonempty boundary descriptions/identifiers.')
    loads = [spec.get('heat_flux_W_m2'), spec.get('total_heat_load_W')]
    if sum(x is not None for x in loads) != 1 or not any(positive(x) for x in loads):
        issues.append('Provide exactly one positive heat_flux_W_m2 or total_heat_load_W.')
    for name in ('maximum_surface_temperature_K', 'inlet_temperature_K'):
        if not positive(spec.get(name)):
            issues.append(f'{name}: provide a finite positive temperature in kelvin.')
    for name in ('solid_material', 'coolant_material', 'objective', 'other_thermal_boundaries'):
        value = spec.get(name)
        if not isinstance(value, str) or not value.strip():
            issues.append(f'{name}: provide an explicit description.')
    for name in ('mass_flow_bounds_kg_s', 'outlet_absolute_pressure_bounds_Pa'):
        value = spec.get(name)
        if (not isinstance(value, list) or len(value) != 2
                or not all(positive(x) for x in value) or value[0] > value[1]):
            issues.append(f'{name}: provide [minimum, maximum], finite positive and ordered.')
    if not isinstance(spec.get('geometry_changes_allowed'), bool):
        issues.append('geometry_changes_allowed: explicitly set true or false.')
    if spec.get('operating_mode') != 'steady':
        issues.append('operating_mode: initial workflow supports steady cases only.')
    if not isinstance(spec.get('material_properties'), dict) or not spec.get('material_properties'):
        issues.append('material_properties: record property models, units and sources for specialist review.')
    if not isinstance(spec.get('acceptance_criteria'), dict) or not spec.get('acceptance_criteria'):
        issues.append('acceptance_criteria: record tolerances and stopping criteria for specialist review.')
    if not isinstance(spec.get('assumptions'), list):
        issues.append('assumptions: provide a list (empty is allowed).')
    return {
        'intake_complete': not issues,
        'issues': issues,
        'simulation_ready': False,
        'pending_reviews': ['toolchain and solver adapter', 'geometry and boundary identities',
                            'material property validity', 'physical model and case settings',
                            'numerical acceptance criteria'],
        'note': 'Structural intake check only. No physical calculation or solver launch.',
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def prepare(root, name, label):
    source, raw, spec = read_spec(root, name)
    approved_package = None
    if spec.get('requirements_review') is not None:
        from requirements.review import verify_handoff
        receipt = spec['requirements_review']
        if not isinstance(receipt, dict) or not isinstance(receipt.get('manifest'), str):
            raise ValueError('requirements_review must identify an approved handoff manifest.')
        approved_package = local_path(root, receipt['manifest']).parent
        verify_handoff(approved_package)
        if source != approved_package / 'project.json':
            raise ValueError('Prepare directly from the verified handoff project.json.')
        if local_path(root, spec['cad_file']) != approved_package / 'source.step':
            raise ValueError('Handoff CAD path does not identify its verified source snapshot.')
    checks = check_spec(root, spec)
    run_id = (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-'
              + (re.sub(r'[^a-zA-Z0-9_-]', '-', label)[:48] or 'request')
              + '-' + uuid.uuid4().hex[:8])
    folder = root / 'runs' / run_id
    folder.mkdir(parents=True)
    (folder / 'project.json').write_bytes(raw)
    inputs = [{'path': 'project.json', 'source': str(source.relative_to(root)),
               'sha256': hashlib.sha256(raw).hexdigest()}]
    if approved_package:
        import shutil
        destination = folder / 'requirements_review'
        destination.mkdir()
        for filename in ('manifest.json', 'source.step', 'model.json', 'requirements.json', 'approval.json', 'project.json'):
            target = destination / filename
            shutil.copyfile(approved_package / filename, target)
            inputs.append({'path': str(target.relative_to(folder)),
                           'source': str((approved_package / filename).relative_to(root)),
                           'sha256': sha256(target)})
    cad = spec.get('cad_file')
    if isinstance(cad, str) and cad.strip():
        try:
            cad_path = local_path(root, cad)
        except ValueError:
            cad_path = None
        if cad_path and cad_path.is_file():
            import shutil
            target = folder / 'inputs' / cad_path.name
            target.parent.mkdir()
            shutil.copyfile(cad_path, target)
            inputs.append({'path': str(target.relative_to(folder)),
                           'source': str(cad_path.relative_to(root)), 'sha256': sha256(target)})
    state = {
        'schema_version': 1, 'run_id': run_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'prepared_only', 'simulation_executed': False,
        'inputs': inputs, 'intake': checks,
        'stages': [{'name': n, 'owner': o, 'status': 'not_started', 'purpose': p}
                   for n, o, p in STAGES],
        'jobs': [],
    }
    write_json(folder / 'workflow.json', state)
    missing = '\n'.join('- ' + item for item in checks['issues']) or '- None found by structural intake check.'
    stages = '\n'.join(f'- {n} — {o}: {p}' for n, o, p in STAGES)
    (folder / 'plan.md').write_text(
        f'# {run_id}\n\nPrepared only; no simulation launched.\n\n'
        '## Scope and decisions\n\nManager records the user request, assumptions, allowed '
        'changes and execution scope here before engineering work. Preparing a request '
        'does not authorize execution.\n\n## Unresolved intake\n\n' + missing +
        '\n\n## Stage ownership and next steps\n\n' + stages +
        '\n\n## Evidence\n\nworkflow.json records snapshot hashes and intake checks. '
        'Use the copied CAD listed there for this run. Record each later job directory '
        'in workflow.json jobs and preserve full logs/fields on disk. The manager updates '
        'stages and this plan; no automatic scheduling or acceptance is implemented.\n')
    return {'run_directory': str(folder.relative_to(root)), **state}


def status(root, name):
    folder = local_path(root, name)
    state = json.loads((folder / 'workflow.json').read_text())
    integrity = []
    for item in state['inputs']:
        path = local_path(folder, item['path'])
        integrity.append({'path': item['path'], 'matches_snapshot':
                          path.is_file() and sha256(path) == item['sha256']})
    return {**state, 'snapshot_integrity': integrity}
