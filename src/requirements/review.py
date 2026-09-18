"""Versioned requirements drafts, explicit visual approval and CAD handoffs."""
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid


class ConflictError(ValueError):
    """The displayed revision no longer matches the stored review."""


def now():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


@contextmanager
def locked(folder):
    folder = Path(folder)
    with (folder / '.review.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield folder


def defaults():
    return {
        'title': '', 'units_confirmed': False, 'solid_material': '',
        'coolant_material': '', 'inlet_temperature_K': None,
        'maximum_surface_temperature_K': None, 'objective': '',
        'temperature_limit_scope': 'heated_surfaces',
        'other_thermal_boundaries': '', 'operating_mode': 'steady',
        'mass_flow_bounds_kg_s': [None, None],
        'outlet_absolute_pressure_bounds_Pa': [None, None],
        'heat_load': {'mode': 'heat_flux_W_m2', 'value': None},
        'heat_direction': 'into_solid', 'geometry_changes_allowed': False,
        'notes': '',
    }


def initialize_review(folder, source_path, model, project=None):
    """Create a new review from a real imported model (test fixtures may be synthetic)."""
    folder, source_path = Path(folder), Path(source_path)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'review.json').exists():
        raise ValueError('Review already exists; create a new versioned directory.')
    (folder / 'inputs').mkdir(exist_ok=True)
    target = folder / 'inputs' / 'source.step'
    if source_path.resolve() != target.resolve():
        if target.exists():
            raise ValueError('Refusing to overwrite an existing source snapshot.')
        shutil.copyfile(source_path, target)
    if file_hash(target) != model['source']['sha256']:
        raise ValueError('STEP changed during import; create the preview again.')
    atomic_json(folder / 'model.json', model)
    requirements = defaults()
    if project:
        for key in requirements:
            if key in project and project[key] is not None:
                requirements[key] = copy.deepcopy(project[key])
        for key in ('heat_flux_W_m2', 'total_heat_load_W'):
            if project.get(key) is not None:
                requirements['heat_load'] = {'mode': key, 'value': project[key]}
        if project.get('heat_flux_W_m2') is not None and project.get('total_heat_load_W') is not None:
            raise ValueError('Project has two heat-load representations; resolve before review.')
        if project.get('pressure_input') is not None:
            requirements['pressure_input'] = copy.deepcopy(project['pressure_input'])
        if project.get('max_pump_pressure_rise_Pa') is not None:
            requirements['max_pump_pressure_rise_Pa'] = project['max_pump_pressure_rise_Pa']
    requirements['units_confirmed'] = False
    draft = {'schema_version': 1, 'revision': 0,
             'model_fingerprint': model['import_fingerprint'],
             'selections': {'inlet': [], 'outlet': [], 'heated': []},
             'requirements': requirements}
    validate_draft_structure(model, draft)
    record = {'schema_version': 1, 'created_at': now(),
              'source_sha256': file_hash(target),
              'model_sha256': file_hash(folder / 'model.json'),
              'draft': draft, 'approval': None}
    atomic_json(folder / 'review.json', record)
    (folder / 'plan.md').write_text(
        '# Visual requirements review\n\nOwner: requirements specialist, coordinated by manager.\n'
        'Source STEP and model.json are versioned snapshots. Display triangles are '
        'for review only, not a simulation mesh.\n\nNext: inspect scale, select inlet, outlet '
        'and heated surfaces; resolve physical values; save draft. The user must explicitly '
        'confirm the current visual/numerical draft before CAD handoff.\n\n'
        'No solver is launched by this workflow. CAD must still verify topology, '
        'port definitions, region extraction and boundary mapping.\n')
    return read_state(folder)


def boundary_map(model):
    return {face['id']: face for face in model['faces'] + model.get('virtual_faces', [])}


def validate_draft_structure(model, draft):
    """Reject corrupt assignments/types even when incomplete physical values are allowed."""
    if not isinstance(draft, dict):
        raise ValueError('Draft must be an object.')
    if draft.get('model_fingerprint') != model['import_fingerprint']:
        raise ConflictError('Boundary IDs refer to a different imported model.')
    selections = draft.get('selections')
    if not isinstance(selections, dict) or set(selections) != {'inlet', 'outlet', 'heated'}:
        raise ValueError('Selections must contain inlet, outlet and heated lists.')
    boundaries, seen = boundary_map(model), set()
    for role, values in selections.items():
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError('Boundary selections must be lists of IDs.')
        if len(values) != len(set(values)):
            raise ValueError('Duplicate boundary selection.')
        for identity in values:
            if identity not in boundaries:
                raise ValueError('Unknown boundary ID: ' + identity)
            if identity in seen:
                raise ValueError('Inlet, outlet and heated selections must not overlap.')
            if role == 'heated' and boundaries[identity]['kind'] != 'cad_face':
                raise ValueError('Virtual port caps cannot receive a solid heat load.')
            seen.add(identity)
    req = draft.get('requirements')
    template = defaults()
    if not isinstance(req, dict) or set(req) - {'pressure_input', 'max_pump_pressure_rise_Pa'} != set(template):
        raise ValueError('Requirements fields do not match the review schema.')
    pressure = req.get('pressure_input')
    if pressure is not None:
        if (not isinstance(pressure, dict)
                or set(pressure) != {'mode', 'bounds_Pa', 'reference_pressure_Pa'}
                or pressure['mode'] not in ('absolute', 'gauge')
                or not isinstance(pressure['bounds_Pa'], list)
                or len(pressure['bounds_Pa']) != 2):
            raise ValueError('Pressure input requires mode, two bounds in Pa and a reference pressure.')
    for key, default in template.items():
        if isinstance(default, str) and not isinstance(req[key], str):
            raise ValueError(key + ' must be text.')
        if isinstance(default, bool) and not isinstance(req[key], bool):
            raise ValueError(key + ' must be a boolean.')
    for key in ('mass_flow_bounds_kg_s', 'outlet_absolute_pressure_bounds_Pa'):
        if not isinstance(req[key], list) or len(req[key]) != 2:
            raise ValueError(key + ' requires [minimum, maximum].')
    load = req['heat_load']
    if not isinstance(load, dict) or set(load) != {'mode', 'value'}:
        raise ValueError('heat_load requires mode and value.')
    if load['mode'] not in ('heat_flux_W_m2', 'total_heat_load_W'):
        raise ValueError('Choose uniform heat flux or total power.')
    # Strict JSON: reject NaN/Infinity anywhere, even in an incomplete draft.
    content_hash(draft)


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def bounds_errors(req):
    """Field-specific diagnostics; incomplete drafts remain saveable."""
    errors = {}
    pump_limit = req.get('max_pump_pressure_rise_Pa')
    if pump_limit is not None and not positive(pump_limit):
        errors['max_pump_pressure_rise'] = 'Enter a maximum pump pressure rise greater than 0 bar, or leave it blank if unspecified.'
    pressure_input = req.get('pressure_input')
    for key, prefix, label, unit in (
        ('mass_flow_bounds_kg_s', 'flow', 'Mass flow', 'kg/s'),
        ('outlet_absolute_pressure_bounds_Pa', 'pressure', 'Outlet pressure', 'bar absolute'),
    ):
        gauge = prefix == 'pressure' and pressure_input and pressure_input['mode'] == 'gauge'
        values = pressure_input['bounds_Pa'] if prefix == 'pressure' and pressure_input else req[key]
        lower, upper = values
        reference = pressure_input['reference_pressure_Pa'] if gauge else None
        display_scale = 100000 if prefix == 'pressure' else 1
        if gauge:
            unit = 'bar gauge'
            if not positive(reference):
                errors['pressure_reference'] = 'Enter an ambient/reference absolute pressure greater than 0 bar to convert gauge pressure.'
        for field, position, value in ((prefix + '_min', 'lower', lower),
                                       (prefix + '_max', 'upper', upper)):
            if value is None:
                errors[field] = f'Enter the {label.lower()} {position} bound in {unit}.'
            elif type(value) not in (int, float) or not math.isfinite(value):
                errors[field] = f'{label} {position} bound must be a finite number in {unit}.'
            elif gauge:
                if positive(reference) and value + reference <= 0:
                    errors[field] = (f'{label} {position} bound corresponds to {(value + reference)/display_scale:g} bar absolute. '
                                     'The converted absolute pressure must be greater than 0 bar.')
            elif value <= 0:
                errors[field] = (f'{label} {position} bound is {value/display_scale:g} {unit}. '
                                 f'Enter a value greater than 0 {unit}.')
                if prefix == 'pressure':
                    errors[field] += (' If you meant gauge pressure, convert it using your '
                                      'ambient/reference pressure.')
        if all(type(x) in (int, float) and math.isfinite(x) for x in values) and lower > upper:
            errors[prefix + '_min'] = (f'{label} lower bound ({lower/display_scale:g} {unit}) exceeds '
                                      f'the upper bound ({upper/display_scale:g} {unit}). Correct the range.')
        if prefix == 'pressure' and pressure_input and not any(k.startswith('pressure_') for k in errors):
            converted = [value + reference for value in values] if gauge else values
            actual = req[key]
            if any(not positive(value) for value in actual) or any(
                    not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9)
                    for value, expected in zip(actual, converted)):
                errors['pressure_min'] = 'Stored absolute pressure does not match the displayed pressure input and reference. Save the pressure fields again.'
            if not gauge and pressure_input['reference_pressure_Pa'] is not None:
                errors['pressure_reference'] = 'An absolute-pressure input must not include a gauge reference.'
    return errors


def approval_issues(model, draft):
    validate_draft_structure(model, draft)
    req, selected = draft['requirements'], draft['selections']
    issues = []
    if model.get('units') != 'mm':
        issues.append('Preview units are unsupported; regenerate in millimetres.')
    if model.get('solid_count') != 1:
        issues.append('Initial review handoff supports one solid; resolve assembly/region scope first.')
    for role in ('inlet', 'outlet', 'heated'):
        if not selected[role]:
            issues.append('Select the ' + role + ' surfaces/openings.')
    if not req['units_confirmed']:
        issues.append('Confirm the displayed millimetre dimensions match the part.')
    for key in ('solid_material', 'coolant_material', 'objective', 'other_thermal_boundaries'):
        if not req[key].strip():
            issues.append('Specify ' + key.replace('_', ' ') + '.')
    for key in ('inlet_temperature_K', 'maximum_surface_temperature_K'):
        if not positive(req[key]):
            issues.append('Specify a positive ' + key + ' in kelvin.')
    if not positive(req['heat_load']['value']):
        issues.append('Specify a positive heat load in the displayed units.')
    issues.extend(bounds_errors(req).values())
    if req['operating_mode'] != 'steady':
        issues.append('Initial handoff supports steady conditions only.')
    if req['heat_direction'] != 'into_solid':
        issues.append('Initial handoff supports heat entering the selected solid surfaces only.')
    if req['temperature_limit_scope'] != 'heated_surfaces':
        issues.append('Temperature limit must apply to the selected heated surfaces in this workflow.')
    if req['geometry_changes_allowed']:
        issues.append('Initial handoff preserves fixed geometry; define a separate design-change scope.')
    return issues


def _load(folder):
    record = json.loads((folder / 'review.json').read_text())
    if file_hash(folder / 'inputs/source.step') != record['source_sha256']:
        raise ConflictError('Copied STEP changed. Create a new review; old approval is invalid.')
    if file_hash(folder / 'model.json') != record['model_sha256']:
        raise ConflictError('Preview changed. Create a new review; old approval is invalid.')
    model = json.loads((folder / 'model.json').read_text())
    if model['source']['sha256'] != record['source_sha256']:
        raise ConflictError('Preview and source STEP do not match.')
    validate_draft_structure(model, record['draft'])
    return record, model


def _state(record, model):
    draft_hash = content_hash(record['draft'])
    approval = record['approval']
    issues = approval_issues(model, record['draft'])
    approved = bool(approval and not issues
                    and approval.get('draft_sha256') == draft_hash
                    and approval.get('source_sha256') == record['source_sha256']
                    and approval.get('model_sha256') == record['model_sha256']
                    and approval.get('revision') == record['draft']['revision']
                    and approval.get('confirmed') is True)
    return {'model': model, 'draft': record['draft'], 'draft_sha256': draft_hash,
            'approval': approval, 'approved': approved, 'issues': issues,
            'field_errors': bounds_errors(record['draft']['requirements'])}


def read_state(folder):
    with locked(folder) as folder:
        return _state(*_load(folder))


def require_revision(record, expected_revision):
    if type(expected_revision) is not int or expected_revision != record['draft']['revision']:
        raise ConflictError('Draft changed in another session. Reload before editing or confirming.')


def save_draft(folder, draft, expected_revision):
    with locked(folder) as folder:
        record, model = _load(folder)
        require_revision(record, expected_revision)
        if not isinstance(draft, dict) or set(draft) != {'selections', 'requirements'}:
            raise ValueError('Submit selections and requirements only.')
        revised = {**record['draft'], **copy.deepcopy(draft),
                   'revision': record['draft']['revision'] + 1}
        validate_draft_structure(model, revised)
        record.update(draft=revised, approval=None)
        atomic_json(folder / 'review.json', record)
        return _state(record, model)


def approve(folder, expected_revision, draft_sha256, confirmed, reviewer):
    """Call only on the user's explicit confirmation of the current displayed draft."""
    with locked(folder) as folder:
        record, model = _load(folder)
        require_revision(record, expected_revision)
        if draft_sha256 != content_hash(record['draft']):
            raise ConflictError('Displayed requirements changed. Reload before confirming.')
        if confirmed is not True or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError('Explicit user confirmation and reviewer name are required.')
        issues = approval_issues(model, record['draft'])
        if issues:
            raise ValueError('Requirements remain unresolved: ' + '; '.join(issues))
        record['approval'] = {
            'confirmed': True, 'reviewer': reviewer.strip(), 'approved_at': now(),
            'revision': expected_revision, 'draft_sha256': draft_sha256,
            'source_sha256': record['source_sha256'], 'model_sha256': record['model_sha256'],
            'scope': 'User confirms displayed boundaries, scale and requirements for CAD preparation only.',
        }
        atomic_json(folder / 'review.json', record)
        return _state(record, model)


def project_for_handoff(destination, draft):
    req, selections = draft['requirements'], draft['selections']
    project = {key: copy.deepcopy(req[key]) for key in (
        'solid_material', 'coolant_material', 'inlet_temperature_K',
        'maximum_surface_temperature_K', 'objective', 'other_thermal_boundaries',
        'temperature_limit_scope', 'operating_mode', 'mass_flow_bounds_kg_s',
        'outlet_absolute_pressure_bounds_Pa', 'geometry_changes_allowed')}
    project.update(schema_version=2, status='requirements_approved_for_cad',
                   cad_file=str((destination / 'source.step').resolve()),
                   heated_faces=selections['heated'], inlet_faces=selections['inlet'],
                   outlet_faces=selections['outlet'], heat_flux_W_m2=None,
                   total_heat_load_W=None, material_properties=None, acceptance_criteria=None,
                   assumptions=[req['notes']] if req['notes'].strip() else [],
                   requirements_review={'manifest': str((destination / 'manifest.json').resolve()),
                                        'draft_sha256': content_hash(draft)})
    project[req['heat_load']['mode']] = req['heat_load']['value']
    if req.get('pressure_input') is not None:
        project['pressure_input'] = copy.deepcopy(req['pressure_input'])
    if req.get('max_pump_pressure_rise_Pa') is not None:
        project['max_pump_pressure_rise_Pa'] = req['max_pump_pressure_rise_Pa']
    return project


def handoff(folder):
    with locked(folder) as folder:
        record, model = _load(folder)
        state = _state(record, model)
        if not state['approved']:
            raise ValueError('Current requirements need explicit user approval before CAD handoff.')
        destination = folder / 'handoffs' / ('revision-' + str(record['draft']['revision'])
                                           + '-' + uuid.uuid4().hex[:8])
        destination.mkdir(parents=True)
        shutil.copyfile(folder / 'inputs/source.step', destination / 'source.step')
        shutil.copyfile(folder / 'model.json', destination / 'model.json')
        atomic_json(destination / 'requirements.json', record['draft'])
        atomic_json(destination / 'approval.json', record['approval'])
        req, selections = record['draft']['requirements'], record['draft']['selections']
        project = project_for_handoff(destination, record['draft'])
        atomic_json(destination / 'project.json', project)
        manifest = {'schema_version': 1, 'created_at': now(),
                    'status': 'approved_for_cad_only', 'simulation_ready': False,
                    'source_sha256': record['source_sha256'],
                    'model_sha256': record['model_sha256'],
                    'import_fingerprint': model['import_fingerprint'],
                    'draft_sha256': state['draft_sha256'], 'approval': record['approval'],
                    'boundary_mapping': [boundary_map(model)[key] | {'role': role}
                                         for role, keys in selections.items() for key in keys],
                    'files': {name: file_hash(destination / name) for name in
                              ('source.step', 'model.json', 'requirements.json', 'approval.json', 'project.json')},
                    'pending': ['CAD topology and port validity', 'fluid-region extraction',
                                'material property sources', 'solver settings and numerical verification']}
        atomic_json(destination / 'manifest.json', manifest)
        return {'handoff_directory': str(destination.resolve()), 'manifest': manifest}


def verify_handoff(folder):
    """Validate a delivered package itself without requiring a running viewer."""
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text())
    expected_files = {'source.step', 'model.json', 'requirements.json', 'approval.json', 'project.json'}
    if set(manifest.get('files', {})) != expected_files:
        raise ValueError('Handoff file list does not match the contract.')
    for name, digest in manifest['files'].items():
        if not (folder / name).is_file() or file_hash(folder / name) != digest:
            raise ConflictError('Handoff snapshot changed: ' + name)
    model = json.loads((folder / 'model.json').read_text())
    draft = json.loads((folder / 'requirements.json').read_text())
    approval = json.loads((folder / 'approval.json').read_text())
    record = {'draft': draft, 'approval': approval, 'source_sha256': file_hash(folder / 'source.step'),
              'model_sha256': file_hash(folder / 'model.json')}
    if (model['source']['sha256'] != record['source_sha256']
            or manifest['draft_sha256'] != content_hash(draft)
            or not _state(record, model)['approved']):
        raise ConflictError('Handoff approval does not match its snapshots.')
    mapping = [boundary_map(model)[key] | {'role': role}
               for role, keys in draft['selections'].items() for key in keys]
    if (manifest.get('source_sha256') != record['source_sha256']
            or manifest.get('model_sha256') != record['model_sha256']
            or manifest.get('import_fingerprint') != model['import_fingerprint']
            or manifest.get('approval') != approval
            or manifest.get('boundary_mapping') != mapping
            or manifest.get('status') != 'approved_for_cad_only'
            or manifest.get('simulation_ready') is not False):
        raise ConflictError('Handoff manifest does not match its approved snapshots.')
    project = json.loads((folder / 'project.json').read_text())
    expected_project = project_for_handoff(folder, draft)
    if project != expected_project:
        raise ConflictError('Exported project does not match the approved requirements.')
    return {'valid': True, 'scope': 'Approved requirements for CAD; no simulation validity claimed.',
            'handoff_directory': str(folder.resolve())}
